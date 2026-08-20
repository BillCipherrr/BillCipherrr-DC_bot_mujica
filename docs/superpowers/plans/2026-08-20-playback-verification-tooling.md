# Playback Verification Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give this repo a repeatable way to verify play/pause/skip/recommend still work after a code change or a dependency upgrade (e.g. `yt-dlp`), via a fast offline pytest suite (Layer A) plus a live smoke-test CLI against a real Discord test server (Layer B).

**Architecture:** Layer A drives the real `MusicCog`/`PlayerView` classes against hand-written fakes for `discord.Interaction`/`VoiceClient`/etc. and a temp SQLite file, so it exercises real control-flow logic with zero network access. Layer B drives the same real `MusicCog` methods against a real Discord bot connection, real voice, and real yt-dlp/YouTube, to catch the class of regression (403s, JS-runtime resolution) that no mock can reproduce.

**Tech Stack:** pytest + pytest-asyncio (Layer A), plain `discord.py`/`asyncio` script (Layer B). No changes to runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-playback-verification-tooling-design.md`

## Global Constraints

- New test code lives under `tests/`; new dev-only dependencies go in `requirements-dev.txt`, never in `requirements.txt` (spec: "kept out of the bot's runtime `requirements.txt`").
- Layer A must never touch the network or spawn a real ffmpeg/Discord-audio process: `yt_dlp.YoutubeDL` and `discord.FFmpegPCMAudio`/`discord.PCMVolumeTransformer` must always be monkeypatched before `play_next` can run.
- Layer B config (new `.env` vars, both required to run it): `VERIFY_GUILD_ID`, `VERIFY_VOICE_CHANNEL_ID`. Optional: `VERIFY_FIXTURE_URLS`.
- Per CLAUDE.md, all in-code comments in this repo are Traditional Chinese (zh-TW); every new file in this plan follows that.
- **This machine's shell has ROS2 sourced globally** (`PYTHONPATH` includes `/opt/ros/humble/...`), which breaks pytest's plugin autoload (`ModuleNotFoundError: No module named 'lark'` from an unrelated `launch_testing` pytest11 entry point) unless `PYTHONPATH` is cleared for the pytest invocation. **Every `pytest` command in this plan and in any docs must be run as `env -u PYTHONPATH pytest ...`.** This was hit and confirmed live while validating this plan.

---

### Task 1: Test harness foundation (dev tooling + fakes + pure-function tests)

**Files:**
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `tests/conftest.py`
- Create: `tests/test_ytdlp_config.py`

**Interfaces:**
- Produces (used by every later Layer A task): fixtures `music_cog`, `fake_bot`, `make_interaction`, `temp_db`, `patch_ytdlp` from `tests/conftest.py`; classes `FakeGuild`, `FakeMember`, `FakeVoiceChannel`, `FakeVoiceClient`, `FakeVoiceState`, `FakeInteraction`, `FakeTextChannel`, `FakeMessage`, `FakeYoutubeDL`, `FakeAudioSource`, `FakeBot`, `FakeUser` (all importable via `from conftest import <Name>` from any file under `tests/`).
- `make_interaction(voice_client="default")` -> `FakeInteraction`: default arg builds a guild with an already-connected `FakeVoiceClient`; pass `voice_client=None` to get a guild with `guild.voice_client is None` (for `ensure_voice_connection`/stale-reconnect tests).
- `patch_ytdlp(result=None, exception=None)`: call inside a test to control what the next `yt_dlp.YoutubeDL(...).extract_info(...)` call returns/raises.
- `temp_db` fixture: redirects `database.DB_PATH` to a per-test temp file and runs `database.setup_database()`; depend on it in any test that calls `play_next`, `get_recommendation`, or `database.*` directly.

- [ ] **Step 1: Create `requirements-dev.txt`**

```
pytest
pytest-asyncio
```

- [ ] **Step 2: Install dev dependencies**

Run: `pip install -r requirements-dev.txt`
Expected: pytest and pytest-asyncio install successfully into the active `DC_bot` conda env.

- [ ] **Step 3: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 4: Create `tests/conftest.py`**

```python
import asyncio
import itertools
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import discord
import pytest
import yt_dlp

import database
from cogs.music import MusicCog

_id_counter = itertools.count(1)


def next_id():
    return next(_id_counter)


class FakeMessage:
    """discord.Message 的替身：只記錄 edit/delete 被呼叫的內容，不做任何網路呼叫。"""

    def __init__(self, content=None, embed=None, view=None):
        self.content = content
        self.embed = embed
        self.view = view
        self.deleted = False
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        for k, v in kwargs.items():
            setattr(self, k, v)

    async def delete(self):
        self.deleted = True


class FakeTextChannel:
    """discord.TextChannel 的替身：send() 只是把訊息記錄下來供測試斷言。"""

    def __init__(self):
        self.sent_messages = []

    async def send(self, content=None, embed=None, view=None):
        msg = FakeMessage(content=content, embed=embed, view=view)
        self.sent_messages.append(msg)
        return msg


class FakeUser:
    def __init__(self, user_id=None, name="TestUser"):
        self.id = user_id or next_id()
        self.name = name
        self.mention = f"<@{self.id}>"


class FakeVoiceState:
    def __init__(self, channel=None):
        self.channel = channel


class FakeMember(FakeUser):
    def __init__(self, user_id=None, name="TestMember", voice_channel=None):
        super().__init__(user_id, name)
        self.voice = FakeVoiceState(voice_channel) if voice_channel else None


class FakeVoiceChannel:
    def __init__(self, channel_id=None, guild=None):
        self.id = channel_id or next_id()
        self.guild = guild
        # 測試用鉤子：依序設定 connect() 要丟出的例外（None 代表成功），
        # 讓 ensure_voice_connection 的重試迴圈可以被決定性地測試
        # （例如 [TimeoutError(), None] 代表第一次逾時、第二次成功）。
        self.connect_outcomes = None

    async def connect(self, timeout=30.0, reconnect=True):
        if self.connect_outcomes:
            outcome = self.connect_outcomes.pop(0)
            if outcome is not None:
                raise outcome
        vc = FakeVoiceClient(channel=self)
        self.guild.voice_client = vc
        return vc


class FakeVoiceClient:
    """discord.VoiceClient 的替身，並強制執行與真實 discord.py 相同的
    「Already playing audio」規則：在前一個來源還沒被 stop()/自然播畢的
    情況下再次呼叫 play() 會丟出 ClientException。"""

    def __init__(self, channel=None):
        self.channel = channel
        self._connected = True
        self._playing = False
        self._paused = False
        self._in_flight = False
        self.play_calls = 0
        self._after = None

    def is_connected(self):
        return self._connected

    def is_playing(self):
        return self._playing

    def is_paused(self):
        return self._paused

    def play(self, source, after=None):
        if self._in_flight:
            raise discord.errors.ClientException("Already playing audio.")
        self._in_flight = True
        self._playing = True
        self._paused = False
        self.play_calls += 1
        self._after = after

    def pause(self):
        self._playing = False
        self._paused = True

    def resume(self):
        self._playing = True
        self._paused = False

    def stop(self):
        was_in_flight = self._in_flight
        after = self._after
        self._in_flight = False
        self._playing = False
        self._paused = False
        self._after = None
        if was_in_flight and after:
            after(None)

    async def move_to(self, channel):
        self.channel = channel

    async def disconnect(self, force=False):
        self._connected = False


class FakeGuild:
    def __init__(self, guild_id=None, voice_client=None):
        self.id = guild_id or next_id()
        self.voice_client = voice_client
        self._members = {}

    def add_member(self, member: FakeMember):
        self._members[member.id] = member

    def get_member(self, user_id):
        return self._members.get(user_id)


class FakeResponse:
    def __init__(self):
        self.deferred = False
        self.sent = []

    async def defer(self, *args, **kwargs):
        self.deferred = True

    async def send_message(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class FakeInteraction:
    def __init__(self, guild, channel, user):
        self.guild = guild
        self.channel = channel
        self.user = user
        self.response = FakeResponse()
        self.followup = FakeFollowup()


class FakeBot:
    def __init__(self):
        self.user = FakeUser(user_id=999, name="MujicaBot")
        self._guilds = {}

    @property
    def loop(self):
        # 只會在 after_playing 的回呼裡被讀取，而該回呼永遠是在目前測試的
        # event loop 內同步執行（見 FakeVoiceClient.stop()），所以即使這是
        # 一般（非 async）的 property，get_running_loop() 在這裡永遠有效。
        return asyncio.get_running_loop()

    def register_guild(self, guild: FakeGuild):
        self._guilds[guild.id] = guild

    def get_guild(self, guild_id):
        return self._guilds.get(guild_id)


@pytest.fixture
def fake_bot():
    return FakeBot()


@pytest.fixture
def music_cog(fake_bot):
    return MusicCog(bot=fake_bot)


@pytest.fixture
def make_interaction(fake_bot):
    """Factory：建立一個註冊在 fake_bot 裡的 FakeInteraction，預設會附帶一個
    已經「連線中」的 FakeVoiceClient；傳入 voice_client=None 可以拿到一個
    guild.voice_client 為 None 的情境（測試 ensure_voice_connection / 語音
    斷線重連邏輯時使用）。"""

    def _make(voice_client="default"):
        vc = FakeVoiceClient() if voice_client == "default" else voice_client
        guild = FakeGuild(voice_client=vc)
        if vc is not None:
            vc.channel = FakeVoiceChannel(guild=guild)
        fake_bot.register_guild(guild)
        channel = FakeTextChannel()
        user = FakeMember(voice_channel=guild.voice_client.channel if vc else None)
        user.guild = guild  # get_recommendation() 會讀取 requester.guild.id
        guild.add_member(user)
        return FakeInteraction(guild=guild, channel=channel, user=user)

    return _make


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """把 database.DB_PATH 導向一個暫存檔並初始化資料表，讓測試可以真的
    呼叫 database.py 的 SQL，而不會動到專案根目錄的 dc_bot.db。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.setup_database()
    return db_path


class FakeYoutubeDL:
    """yt_dlp.YoutubeDL 的替身：完全不連網路，回傳/丟出目前測試透過
    patch_ytdlp fixture 設定好的結果。"""

    _next_result = None
    _next_exception = None

    def __init__(self, opts=None):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False):
        if FakeYoutubeDL._next_exception is not None:
            raise FakeYoutubeDL._next_exception
        result = dict(FakeYoutubeDL._next_result or {})
        result.setdefault("url", "https://stream.example.com/audio.m4a")
        result.setdefault("title", "Fake Song")
        result.setdefault("duration", 120)
        result.setdefault("http_headers", {})
        return result


@pytest.fixture
def patch_ytdlp(monkeypatch):
    def _set(result=None, exception=None):
        FakeYoutubeDL._next_result = result
        FakeYoutubeDL._next_exception = exception

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    yield _set
    FakeYoutubeDL._next_result = None
    FakeYoutubeDL._next_exception = None


class FakeAudioSource:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def cleanup(self):
        pass


@pytest.fixture(autouse=True)
def patch_discord_audio(monkeypatch):
    """避免 play_next 真的產生 ffmpeg 子行程 / 建立真的音訊來源物件。"""
    monkeypatch.setattr(discord, "FFmpegPCMAudio", FakeAudioSource)
    monkeypatch.setattr(discord, "PCMVolumeTransformer", FakeAudioSource)


@pytest.fixture(autouse=True)
async def cleanup_pending_tasks(music_cog):
    """play_next 在佇列播完時會排程一個 300 秒的斷線計時器；測試結束後
    主動取消，避免留下 pending task 造成警告或拖慢測試結束。"""
    yield
    for guild_id in list(music_cog.disconnect_timers.keys()):
        music_cog.cancel_disconnect_timer(guild_id)
    for guild_id in list(music_cog.progress_tasks.keys()):
        music_cog.stop_progress_task(guild_id)
```

- [ ] **Step 5: Create `tests/test_ytdlp_config.py`**

```python
import cogs.music as music_module


def test_resolve_node_path_prefers_newest_nvm_version(monkeypatch):
    monkeypatch.setattr(
        music_module.glob,
        "glob",
        lambda pattern: [
            "/home/user/.nvm/versions/node/v18.20.0/bin/node",
            "/home/user/.nvm/versions/node/v20.11.0/bin/node",
        ],
    )
    monkeypatch.setattr(music_module.shutil, "which", lambda name: "/usr/bin/node")

    assert music_module._resolve_node_path() == "/home/user/.nvm/versions/node/v20.11.0/bin/node"


def test_resolve_node_path_falls_back_to_path_when_no_nvm(monkeypatch):
    monkeypatch.setattr(music_module.glob, "glob", lambda pattern: [])
    monkeypatch.setattr(music_module.shutil, "which", lambda name: "/usr/bin/node")

    assert music_module._resolve_node_path() == "/usr/bin/node"


def test_resolve_node_path_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr(music_module.glob, "glob", lambda pattern: [])
    monkeypatch.setattr(music_module.shutil, "which", lambda name: None)

    assert music_module._resolve_node_path() is None


def test_build_ffmpeg_options_injects_user_agent_and_headers():
    song = {
        "http_headers": {
            "User-Agent": "Mozilla/5.0 Test",
            "Referer": "https://example.com",
            "Accept-Encoding": "gzip",  # 必須被排除在 -headers 區塊之外
        }
    }
    opts = music_module.build_ffmpeg_options(song)
    assert "-user_agent" in opts["before_options"]
    assert "Mozilla/5.0 Test" in opts["before_options"]
    assert "Referer: https://example.com" in opts["before_options"]
    assert "Accept-Encoding" not in opts["before_options"].split("-headers")[-1]
    assert "-reconnect_on_http_error 4xx,5xx" in opts["before_options"]


def test_build_ffmpeg_options_no_headers_leaves_base_options_intact():
    opts = music_module.build_ffmpeg_options({})
    assert "-user_agent" not in opts["before_options"]
    assert opts["before_options"].startswith("-reconnect 1 -reconnect_streamed 1")


def test_normalize_youtube_url_expands_short_link():
    assert (
        music_module.normalize_youtube_url("https://youtu.be/abc123?t=5")
        == "https://www.youtube.com/watch?v=abc123?t=5"
    )


def test_extract_video_id_from_standard_url():
    assert music_module.extract_video_id("https://www.youtube.com/watch?v=abc123&list=xyz") == "abc123"


def test_extract_video_id_from_short_url():
    assert music_module.extract_video_id("https://youtu.be/abc123") == "abc123"


def test_normalize_title_for_dedup_strips_punctuation_and_case():
    assert music_module.normalize_title_for_dedup(
        "  Song Title!! (Official MV) "
    ) == music_module.normalize_title_for_dedup("song title official mv")
```

- [ ] **Step 6: Run the tests**

Run: `env -u PYTHONPATH pytest tests/test_ytdlp_config.py -v`
Expected: 9 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add requirements-dev.txt pytest.ini tests/conftest.py tests/test_ytdlp_config.py
git commit -m "test: add pytest harness and pure-function coverage for yt-dlp config helpers"
```

---

### Task 2: `play_next` state machine tests

**Files:**
- Create: `tests/test_play_next_state_machine.py`

**Interfaces:**
- Consumes: `music_cog`, `make_interaction`, `patch_ytdlp`, `temp_db` fixtures and `FakeVoiceChannel`, `FakeVoiceState` classes from `tests/conftest.py` (Task 1).

- [ ] **Step 1: Write the tests**

```python
import asyncio

import database
from views.player_view import LoopMode


async def test_play_next_plays_first_song(music_cog, make_interaction, patch_ytdlp, temp_db):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    queue = music_cog.get_queue(guild_id)
    queue.append({"url": "https://www.youtube.com/watch?v=aaa", "title": "Song A", "requester": interaction.user})

    patch_ytdlp(result={"url": "https://stream.example/a.m4a", "title": "Song A (resolved)", "duration": 100})

    await music_cog.play_next(interaction)

    vc = interaction.guild.voice_client
    assert vc.play_calls == 1
    assert vc.is_playing()
    current = music_cog.get_current_song(guild_id)
    assert current["title"] == "Song A (resolved)"
    assert len(interaction.channel.sent_messages) == 1  # 播放器 embed 訊息


async def test_loop_song_requeues_current_song_at_front(music_cog, make_interaction, patch_ytdlp, temp_db):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    music_cog.set_loop_mode(guild_id, LoopMode.SONG)
    current = {"url": "https://www.youtube.com/watch?v=current", "title": "Currently Playing", "requester": interaction.user}
    music_cog.set_current_song(guild_id, current)
    queue = music_cog.get_queue(guild_id)
    queue.append({"url": "https://www.youtube.com/watch?v=next", "title": "Next Song", "requester": interaction.user})

    patch_ytdlp(result={"title": "Currently Playing", "url": "https://stream.example/a"})
    await music_cog.play_next(interaction)

    # SONG 模式：正在播放的歌會被放回佇列「最前面」，所以會立刻再播一次
    # （這就是「單曲循環」的意思）。
    assert music_cog.get_current_song(guild_id)["title"] == "Currently Playing"
    assert list(music_cog.get_queue(guild_id))[0]["title"] == "Next Song"


async def test_loop_queue_requeues_current_song_at_back(music_cog, make_interaction, patch_ytdlp, temp_db):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    music_cog.set_loop_mode(guild_id, LoopMode.QUEUE)
    current = {"url": "https://www.youtube.com/watch?v=current", "title": "Currently Playing", "requester": interaction.user}
    music_cog.set_current_song(guild_id, current)
    queue = music_cog.get_queue(guild_id)
    queue.append({"url": "https://www.youtube.com/watch?v=next", "title": "Next Song", "requester": interaction.user})

    patch_ytdlp(result={"title": "Next Song", "url": "https://stream.example/b"})
    await music_cog.play_next(interaction)

    assert music_cog.get_current_song(guild_id)["title"] == "Next Song"
    assert list(music_cog.get_queue(guild_id))[0]["title"] == "Currently Playing"


async def test_queue_exhaustion_sends_ended_message_and_starts_disconnect_timer(
    music_cog, make_interaction, patch_ytdlp, temp_db
):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    # 「播放佇列已結束」訊息是透過「編輯」既有的播放器訊息送出的，所以要先
    # 真的播一首歌（建立那則訊息），再讓佇列耗盡。
    queue = music_cog.get_queue(guild_id)
    queue.append({"url": "https://www.youtube.com/watch?v=aaa", "title": "Song A", "requester": interaction.user})
    patch_ytdlp(result={"title": "Song A", "url": "https://stream.example/a"})
    await music_cog.play_next(interaction)
    player_message = music_cog.get_player_message(guild_id)
    assert player_message is not None

    await music_cog.play_next(interaction)  # 佇列現在是空的 -> 走結束流程

    assert music_cog.get_current_song(guild_id) is None
    assert player_message.edits and player_message.edits[-1]["content"] == "播放佇列已結束。"
    assert music_cog.get_player_message(guild_id) is None
    assert guild_id in music_cog.disconnect_timers


async def test_recommend_mode_autoplays_when_queue_empties(music_cog, make_interaction, patch_ytdlp, temp_db):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    music_cog.set_loop_mode(guild_id, LoopMode.RECOMMEND)
    current = {"url": "https://www.youtube.com/watch?v=current", "title": "Currently Playing", "requester": interaction.user}
    music_cog.set_current_song(guild_id, current)
    # 佇列是空的 -> play_next 應該呼叫 get_recommendation() 並繼續播放

    # 先讓這個使用者「聽過」一首歌，讓 get_recommendation() 的第一階段
    # （個人歷史）找得到它，接著把它推出「最近 20 首」去重視窗——否則它會
    # 跟自己去重、導致 get_recommendation() 拋例外，讓這個測試因為錯誤的
    # 原因（例外路徑而非真的推薦成功並繼續播放）通過。
    database.log_song_play(guild_id, interaction.user.id, {"url": "https://www.youtube.com/watch?v=rec1", "title": "Recommended Song", "duration": 80})
    database.log_song_play(guild_id, interaction.user.id, {"url": "https://www.youtube.com/watch?v=rec1", "title": "Recommended Song", "duration": 80})
    conn = database.get_db_connection()
    conn.execute("UPDATE play_history SET played_at = 1 WHERE guild_id = ?", (guild_id,))
    conn.commit()
    conn.close()
    for i in range(20):
        database.log_song_play(
            guild_id, interaction.user.id, {"url": f"https://www.youtube.com/watch?v=filler{i}", "title": f"Filler {i}", "duration": 60}
        )

    patch_ytdlp(result={"title": "Recommended Song", "url": "https://stream.example/rec"})
    await music_cog.play_next(interaction)
    # play_next 的 RECOMMEND 分支是用 asyncio.create_task(self.play_next(...))
    # 排程後續播放，而不是直接 await；那個任務自己的 play_next() 又會透過
    # 「真的」thread-pool executor（loop.run_in_executor）解析串流，所以單純
    # `await asyncio.sleep(0)` 讓出控制權不足以保證它已經跑完，要等真實時間。
    await asyncio.sleep(0.1)

    assert music_cog.get_current_song(guild_id) is not None
    assert music_cog.get_current_song(guild_id)["title"] == "Recommended Song"
    vc = interaction.guild.voice_client
    assert vc.play_calls == 1


async def test_play_next_reconnects_when_voice_client_stale_and_member_in_channel(
    music_cog, make_interaction, patch_ytdlp, temp_db
):
    from conftest import FakeVoiceChannel, FakeVoiceState

    interaction = make_interaction(voice_client=None)
    guild_id = interaction.guild.id
    voice_channel = FakeVoiceChannel(guild=interaction.guild)
    interaction.user.voice = FakeVoiceState(voice_channel)

    queue = music_cog.get_queue(guild_id)
    queue.append({"url": "https://www.youtube.com/watch?v=aaa", "title": "Song A", "requester": interaction.user})
    patch_ytdlp(result={"title": "Song A", "url": "https://stream.example/a"})

    await music_cog.play_next(interaction)

    assert interaction.guild.voice_client is not None
    assert interaction.guild.voice_client.play_calls == 1


async def test_play_next_gives_up_when_voice_client_stale_and_no_member_channel(
    music_cog, make_interaction, temp_db
):
    interaction = make_interaction(voice_client=None)
    guild_id = interaction.guild.id
    interaction.user.voice = None  # 使用者不在任何語音頻道

    queue = music_cog.get_queue(guild_id)
    queue.append({"url": "https://www.youtube.com/watch?v=aaa", "title": "Song A", "requester": interaction.user})

    await music_cog.play_next(interaction)

    assert music_cog.get_current_song(guild_id) is None
    assert any("找不到可重新連線的頻道" in (m.content or "") for m in interaction.channel.sent_messages)
```

- [ ] **Step 2: Run the tests**

Run: `env -u PYTHONPATH pytest tests/test_play_next_state_machine.py -v`
Expected: 7 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_play_next_state_machine.py
git commit -m "test: cover play_next loop-mode requeue, queue exhaustion, recommend autoplay, and stale-voice reconnect"
```

---

### Task 3: Play-lock race, retry throttling, and `ensure_voice_connection` tests

**Files:**
- Create: `tests/test_retry_and_locks.py`

**Interfaces:**
- Consumes: `music_cog`, `make_interaction`, `patch_ytdlp`, `temp_db` fixtures and `FakeGuild`, `FakeVoiceChannel` classes from `tests/conftest.py` (Task 1).

- [ ] **Step 1: Write the tests**

```python
import asyncio

import discord
import pytest

import cogs.music as music_module
from conftest import FakeGuild, FakeVoiceChannel


async def test_concurrent_play_next_and_after_playing_dont_double_play(
    music_cog, make_interaction, patch_ytdlp, temp_db
):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    queue = music_cog.get_queue(guild_id)
    queue.append({"url": "https://www.youtube.com/watch?v=aaa", "title": "Song A", "requester": interaction.user})
    queue.append({"url": "https://www.youtube.com/watch?v=bbb", "title": "Song B", "requester": interaction.user})

    patch_ytdlp(result={"url": "https://stream.example/x.m4a", "title": "Resolved", "duration": 100})

    # 模擬 play_lock 被加上去要修的那個確切競態：after_playing 的成功回呼
    # 重新進入 play_next()，同時又有別的東西也對同一個 guild 呼叫 play_next()。
    await asyncio.gather(
        music_cog.play_next(interaction),
        music_cog._handle_after_playing(interaction, guild_id, None),
    )

    vc = interaction.guild.voice_client
    # play_lock 必須完整地把兩次呼叫序列化：先跑的那個會播 Song A，並讓假
    # voice client 保持在「in flight」狀態（沒有任何東西呼叫它的 stop()），
    # 所以第二次呼叫嘗試播 Song B 時，一定會撞上 _play_next_locked 裡既有的
    # 「Already playing audio」ClientException 處理，安靜放棄而不是重複播放
    # 或是讓例外從 gather() 冒出來。如果 play_lock 被拿掉，這裡就會變成不
    # 確定的競態，而不是穩定得到 1。
    assert vc.play_calls == 1

    import database

    conn = database.get_db_connection()
    row_count = conn.execute(
        "SELECT COUNT(*) FROM play_history WHERE guild_id = ?", (guild_id,)
    ).fetchone()[0]
    conn.close()
    assert row_count == 1  # 只有 Song A 的播放被記錄過


async def test_retry_after_failure_stops_at_max_consecutive_failures(
    music_cog, make_interaction, monkeypatch
):
    monkeypatch.setattr(music_module, "MAX_CONSECUTIVE_PLAY_FAILURES", 3)

    interaction = make_interaction()
    guild_id = interaction.guild.id
    music_cog.set_current_song(guild_id, {"title": "Doomed Song", "url": "https://x", "requester": interaction.user})
    music_cog.consecutive_play_failures[guild_id] = 2  # 再一次就達到上限

    await music_cog._retry_after_failure(interaction, guild_id)  # 這次會把失敗次數推到 3 == 上限

    assert music_cog.consecutive_play_failures[guild_id] == 0
    assert music_cog.get_current_song(guild_id) is None
    assert any("已停止自動播放" in (msg.content or "") for msg in interaction.channel.sent_messages)


async def test_retry_after_failure_reschedules_below_cap(music_cog, make_interaction, monkeypatch):
    monkeypatch.setattr(music_module, "PLAY_FAILURE_RETRY_DELAY", 0)
    monkeypatch.setattr(music_module, "MAX_CONSECUTIVE_PLAY_FAILURES", 3)

    interaction = make_interaction()
    guild_id = interaction.guild.id

    scheduled = []

    def fake_create_task(coro, *a, **kw):
        scheduled.append(coro)
        coro.close()  # 不真的去跑 play_next()，只確認有排程一次重試
        return None

    # cogs.music 是透過共用的 asyncio 模組物件呼叫 asyncio.create_task(...)，
    # 所以這裡是在這個測試執行期間對整個process 動態替換它（monkeypatch 在
    # teardown 時會還原）。這裡是安全的，因為 _retry_after_failure 內唯一的
    # `await asyncio.sleep(0)` 期間，這個單執行緒的 loop 上不會有其他東西在跑。
    monkeypatch.setattr(music_module.asyncio, "create_task", fake_create_task)

    await music_cog._retry_after_failure(interaction, guild_id)

    assert music_cog.consecutive_play_failures[guild_id] == 1
    assert len(scheduled) == 1
    assert not any("已停止自動播放" in (msg.content or "") for msg in interaction.channel.sent_messages)


async def test_ensure_voice_connection_connects_fresh(music_cog):
    guild = FakeGuild(voice_client=None)
    channel = FakeVoiceChannel(guild=guild)

    vc = await music_cog.ensure_voice_connection(channel)

    assert vc.is_connected()
    assert guild.voice_client is vc


async def test_ensure_voice_connection_retries_once_on_timeout_then_succeeds(music_cog, monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(music_module.asyncio, "sleep", no_sleep)

    guild = FakeGuild(voice_client=None)
    channel = FakeVoiceChannel(guild=guild)
    channel.connect_outcomes = [asyncio.TimeoutError(), None]

    vc = await music_cog.ensure_voice_connection(channel)

    assert vc.is_connected()


async def test_ensure_voice_connection_raises_actionable_error_on_4017(music_cog):
    guild = FakeGuild(voice_client=None)
    channel = FakeVoiceChannel(guild=guild)
    channel.connect_outcomes = [discord.errors.ConnectionClosed(None, shard_id=0, code=4017)]

    with pytest.raises(RuntimeError, match="4017"):
        await music_cog.ensure_voice_connection(channel)
```

- [ ] **Step 2: Run the tests**

Run: `env -u PYTHONPATH pytest tests/test_retry_and_locks.py -v`
Expected: 6 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_retry_and_locks.py
git commit -m "test: cover play_lock race serialization, failure-retry throttling, and ensure_voice_connection retries/4017"
```

---

### Task 4: Recommendation tier/dedup tests

**Files:**
- Create: `tests/test_recommendation.py`

**Interfaces:**
- Consumes: `music_cog`, `make_interaction`, `temp_db` fixtures from `tests/conftest.py` (Task 1).

- [ ] **Step 1: Write the tests**

```python
import database
import cogs.music as music_module


async def test_recommendation_prefers_user_history_over_guild_top(music_cog, make_interaction, temp_db):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    user_song_url = "https://www.youtube.com/watch?v=user_fav"
    guild_song_url = "https://www.youtube.com/watch?v=guild_fav"

    # 使用者自己聽過的歌（第一階段）
    database.log_song_play(guild_id, interaction.user.id, {"url": user_song_url, "title": "My Favorite", "duration": 90})
    # 別人聽過、更熱門的歌（第二階段）—— 因為第一階段已經有候選，應該被忽略
    database.log_song_play(guild_id, 555, {"url": guild_song_url, "title": "Guild Favorite", "duration": 90})
    database.log_song_play(guild_id, 555, {"url": guild_song_url, "title": "Guild Favorite", "duration": 90})
    conn = database.get_db_connection()
    conn.execute("UPDATE play_history SET played_at = 1 WHERE guild_id = ?", (guild_id,))
    conn.commit()
    conn.close()
    for i in range(20):
        database.log_song_play(guild_id, 555, {"url": f"https://www.youtube.com/watch?v=filler{i}", "title": f"Filler {i}", "duration": 60})

    rec = await music_cog.get_recommendation({"url": "https://www.youtube.com/watch?v=current"}, interaction.user)
    assert rec["_rec_source"] == "user_history"
    assert rec["url"] == user_song_url


async def test_recommendation_falls_back_to_guild_top(music_cog, make_interaction, temp_db):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    popular_url = "https://www.youtube.com/watch?v=ccc"

    # 幫「另一個」使用者（555，不是 interaction.user）建立歷史，讓第一階段
    # （個人歷史）對 interaction.user 是空的，落到第二階段（伺服器熱門）。
    # 目標歌曲播兩次讓它在 play_count 上贏過下面 20 首填充歌，接著把它的
    # played_at 推到很久以前——否則它會是「剛剛播過」的歌，被最近 20 首的
    # 去重視窗排除掉（我們才剛把它記錄進歷史）。
    database.log_song_play(guild_id, 555, {"url": popular_url, "title": "Popular Song", "duration": 90})
    database.log_song_play(guild_id, 555, {"url": popular_url, "title": "Popular Song", "duration": 90})
    conn = database.get_db_connection()
    conn.execute("UPDATE play_history SET played_at = 1 WHERE guild_id = ?", (guild_id,))
    conn.commit()
    conn.close()
    for i in range(20):
        database.log_song_play(
            guild_id, 555, {"url": f"https://www.youtube.com/watch?v=filler{i}", "title": f"Filler {i}", "duration": 60}
        )

    rec = await music_cog.get_recommendation(
        {"url": "https://www.youtube.com/watch?v=aaa", "title": "Current Song"}, interaction.user
    )
    assert rec["_rec_source"] == "guild_top"
    assert rec["url"] == popular_url


async def test_recommendation_excludes_song_already_in_queue(music_cog, make_interaction, temp_db):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    only_candidate_url = "https://www.youtube.com/watch?v=only_candidate"

    database.log_song_play(guild_id, interaction.user.id, {"url": only_candidate_url, "title": "Only Candidate", "duration": 90})
    conn = database.get_db_connection()
    conn.execute("UPDATE play_history SET played_at = 1 WHERE guild_id = ?", (guild_id,))
    conn.commit()
    conn.close()
    for i in range(20):
        database.log_song_play(guild_id, interaction.user.id, {"url": f"https://www.youtube.com/watch?v=filler{i}", "title": f"Filler {i}", "duration": 60})

    # 已經在佇列裡了 -> 即使是使用者唯一的真實歷史候選，也不該被再推薦一次
    music_cog.get_queue(guild_id).append({"url": only_candidate_url, "title": "Only Candidate"})

    with __import__("pytest").raises(Exception, match="YouTube API 未初始化"):
        await music_cog.get_recommendation({"url": "https://www.youtube.com/watch?v=current"}, interaction.user)


async def test_recommendation_falls_back_to_youtube_api(music_cog, make_interaction, temp_db, monkeypatch):
    interaction = make_interaction()

    class FakeSearchRequest:
        def execute(self):
            return {
                "items": [
                    {"id": {"videoId": "yt_api_pick"}, "snippet": {"title": "From YouTube API"}},
                ]
            }

    class FakeSearch:
        def list(self, **params):
            return FakeSearchRequest()

    class FakeYoutubeClient:
        def search(self):
            return FakeSearch()

    monkeypatch.setattr(music_module, "youtube", FakeYoutubeClient())

    rec = await music_cog.get_recommendation(
        {"url": "https://www.youtube.com/watch?v=current", "title": "Current Song"}, interaction.user
    )
    assert rec["_rec_source"] == "youtube_api"
    assert rec["url"] == "https://www.youtube.com/watch?v=yt_api_pick"
    assert rec["title"] == "From YouTube API"
```

- [ ] **Step 2: Run the tests**

Run: `env -u PYTHONPATH pytest tests/test_recommendation.py -v`
Expected: 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_recommendation.py
git commit -m "test: cover recommendation tier ordering (user/guild/youtube) and dedup exclusion"
```

---

### Task 5: Pause/resume/skip button tests

**Files:**
- Create: `tests/test_pause_resume_skip.py`

**Interfaces:**
- Consumes: `music_cog`, `make_interaction`, `patch_ytdlp`, `temp_db` fixtures from `tests/conftest.py` (Task 1).

- [ ] **Step 1: Write the tests**

```python
import asyncio

from views.player_view import PlayerView


async def test_pause_resume_position_tracking(music_cog, make_interaction, patch_ytdlp, temp_db):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    queue = music_cog.get_queue(guild_id)
    queue.append({"url": "https://www.youtube.com/watch?v=aaa", "title": "Song A", "requester": interaction.user})
    patch_ytdlp(result={"url": "https://stream.example/a.m4a", "title": "Song A", "duration": 100})
    await music_cog.play_next(interaction)

    view = music_cog.get_player_view(guild_id)
    assert isinstance(view, PlayerView)

    pos_before = music_cog.get_current_position(guild_id)
    await view.pause_resume_button.callback(interaction)
    vc = interaction.guild.voice_client
    assert vc.is_paused()
    pos_after_pause = music_cog.get_current_position(guild_id)
    assert pos_after_pause >= pos_before

    await asyncio.sleep(0.05)
    pos_still = music_cog.get_current_position(guild_id)
    assert pos_still == pos_after_pause  # 暫停時位置應該凍結不動

    await view.pause_resume_button.callback(interaction)
    assert vc.is_playing()


async def test_skip_button_stops_voice_client_when_playing(music_cog, make_interaction, patch_ytdlp, temp_db):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    queue = music_cog.get_queue(guild_id)
    queue.append({"url": "https://www.youtube.com/watch?v=aaa", "title": "Song A", "requester": interaction.user})
    patch_ytdlp(result={"title": "Song A", "url": "https://stream.example/a"})
    await music_cog.play_next(interaction)

    vc = interaction.guild.voice_client
    assert vc.is_playing()

    view = music_cog.get_player_view(guild_id)
    await view.skip_button.callback(interaction)

    assert vc.is_playing() is False
    assert interaction.response.sent, "skip 應該要透過 response.send_message 回應"
    # vc.stop() 會同步觸發 after_playing()，它又會透過 run_coroutine_threadsafe
    # 排程 _handle_after_playing()；這裡等一下讓它跑完，避免變成漏到下一個
    # 測試的 pending task。
    await asyncio.sleep(0.05)


async def test_skip_button_noop_when_nothing_playing(music_cog, make_interaction):
    interaction = make_interaction()
    view = PlayerView(music_cog, interaction)
    vc = interaction.guild.voice_client
    assert not vc.is_playing() and not vc.is_paused()

    await view.skip_button.callback(interaction)

    assert vc.play_calls == 0
    assert interaction.response.sent
```

- [ ] **Step 2: Run the tests**

Run: `env -u PYTHONPATH pytest tests/test_pause_resume_skip.py -v`
Expected: 3 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pause_resume_skip.py
git commit -m "test: cover pause/resume position bookkeeping and skip button behavior"
```

---

### Task 6: Layer B — live smoke-test CLI

**Files:**
- Create: `scripts/verify_playback.py`
- Modify: `CLAUDE.md` (document the two new optional env vars, in the existing "Required environment variables" list's style)

**Interfaces:**
- Consumes: real `MusicCog`, `_resolve_node_path` from `cogs/music.py`; real `LoopMode` from `views/player_view.py`; real `database.py`.
- Produces: a standalone script, `python scripts/verify_playback.py`, exit code 0 on all steps passing, 1 otherwise.

- [ ] **Step 1: Add the new env vars to `CLAUDE.md`**

In the "### Required environment variables (`.env`, loaded via python-dotenv)" section, add after the existing `MUSIC_DEBUG` bullet:

```markdown
- `VERIFY_GUILD_ID` / `VERIFY_VOICE_CHANNEL_ID` — optional; only needed to run `scripts/verify_playback.py` (the live playback smoke test). Must point at a real Discord test server / voice channel the bot is already a member of.
- `VERIFY_FIXTURE_URLS` — optional; comma-separated override for `scripts/verify_playback.py`'s built-in fixture YouTube URLs.
```

- [ ] **Step 2: Create `scripts/verify_playback.py`**

```python
#!/usr/bin/env python3
"""針對真實 Discord 測試伺服器的點歌/暫停/下一首/推薦系統煙霧測試。這是
播放驗證工具的 Layer B（見
docs/superpowers/specs/2026-08-20-playback-verification-tooling-design.md）：
Layer A（`pytest tests/`）會 mock 掉 yt-dlp/Discord，跑起來只要幾毫秒；
這支腳本會打真的 yt-dlp/YouTube/Discord 語音，大約需要一分鐘，所以是在升級
yt-dlp/discord.py 之後，或是要信任一個真的動到播放邏輯的修改之前該跑的那個。

用法：
    env -u PYTHONPATH python scripts/verify_playback.py

需要在 .env 設定：
    DISCORD_TOKEN            （bot 本來就需要）
    VERIFY_GUILD_ID           測試伺服器 ID；bot 必須已經是該伺服器成員
    VERIFY_VOICE_CHANNEL_ID   該伺服器裡要加入的語音頻道 ID

選用：
    VERIFY_FIXTURE_URLS       逗號分隔，覆寫內建的兩首測試用 YouTube 網址
                              （萬一其中一首哪天下架了）
"""
import asyncio
import os
import sys
import time
import traceback

import discord
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database  # noqa: E402
from cogs.music import MusicCog, _resolve_node_path  # noqa: E402
from views.player_view import LoopMode  # noqa: E402

# 寫進獨立的暫存資料庫而不是正式的 dc_bot.db，避免測試用的假播放紀錄污染
# 真實的 /history 統計或推薦排序，但仍然是走 database.py 真正的讀寫邏輯
# （沒有被 mock 掉）。
database.DB_PATH = "./dc_bot_verify.db"

DEFAULT_FIXTURES = [
    "https://www.youtube.com/watch?v=jNQXAC9IdE",  # "Me at the zoo"，YouTube 史上第一支影片，19 秒，非常穩定
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # 存活多年的知名影片，約 3.5 分鐘
]

STEP_TIMEOUT = 20  # 等待某個非同步播放效果出現的秒數上限


class LiveResponse:
    async def defer(self, *args, **kwargs):
        pass

    async def send_message(self, content=None, **kwargs):
        print(f"    [interaction.response] {content}")


class LiveFollowup:
    async def send(self, content=None, **kwargs):
        print(f"    [interaction.followup] {content}")


class FixtureRequester:
    """MusicCog 附加在每首歌上的「requester」替身。這樣就不需要特殊的
    Members 特權 intent 去查真的 discord.Member —— MusicCog 只會讀取
    .id / .mention / .guild。"""

    def __init__(self, guild, user_id, mention):
        self.id = user_id
        self.mention = mention
        self.guild = guild


class LiveInteraction:
    """把 discord.Interaction 的介面 duck-type 出剛好夠 MusicCog 的方法用
    （只會碰 .guild / .channel / .user / .response / .followup）。這裡直接
    重用「真的」語音頻道物件當作 .channel，因為 discord.VoiceChannel 本身
    就是 Messageable（有 .send()），所以播放器 embed／訊息會真的送進該語音
    頻道的文字聊天室，方便人工肉眼確認。"""

    def __init__(self, guild, channel, user):
        self.guild = guild
        self.channel = channel
        self.user = user
        self.response = LiveResponse()
        self.followup = LiveFollowup()


class StepResult:
    def __init__(self, name):
        self.name = name
        self.passed = None  # True/False/None（略過）
        self.detail = ""


async def wait_until(predicate, timeout=STEP_TIMEOUT, interval=0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def run_scenario(music_cog, interaction, fixtures, results):
    guild_id = interaction.guild.id
    vc = interaction.guild.voice_client

    # --- Step 1: 點歌 ---
    step = StepResult("Play")
    results.append(step)
    try:
        node_path = _resolve_node_path()
        warn = "（警告：會退回容易被 403 的 android_vr client）" if not node_path else ""
        print(f"  node runtime 解析結果: {node_path!r}{warn}")
        music_cog.get_queue(guild_id).append(
            {"url": fixtures[0], "title": "fixture-1", "requester": interaction.user}
        )
        await music_cog.play_next(interaction)
        ok = await wait_until(lambda: vc.is_playing())
        if not ok:
            raise AssertionError("voice_client 在時限內沒有進入 is_playing() 狀態")
        step.passed = True
        step.detail = f"目前播放中: {music_cog.get_current_song(guild_id).get('title')!r}"
    except Exception as e:
        step.passed = False
        step.detail = f"{type(e).__name__}: {e}"
        traceback.print_exc()

    # --- Step 2: 暫停/繼續 ---
    step = StepResult("Pause/Resume")
    results.append(step)
    if not results[0].passed:
        step.passed = None
        step.detail = "略過：Play 失敗"
    else:
        try:
            view = music_cog.get_player_view(guild_id)
            await view.pause_resume_button.callback(interaction)
            if not vc.is_paused():
                raise AssertionError("按下暫停後 voice_client 沒有進入 is_paused()")
            pos1 = music_cog.get_current_position(guild_id)
            await asyncio.sleep(2)
            pos2 = music_cog.get_current_position(guild_id)
            if pos2 != pos1:
                raise AssertionError(f"暫停中位置卻前進了 ({pos1} -> {pos2})")
            await view.pause_resume_button.callback(interaction)
            if not vc.is_playing():
                raise AssertionError("按下繼續後 voice_client 沒有回到播放狀態")
            step.passed = True
            step.detail = "暫停時位置有凍結、繼續播放成功"
        except Exception as e:
            step.passed = False
            step.detail = f"{type(e).__name__}: {e}"
            traceback.print_exc()

    # --- Step 3: 下一首 ---
    step = StepResult("Skip")
    results.append(step)
    if not results[0].passed:
        step.passed = None
        step.detail = "略過：Play 失敗"
    else:
        try:
            music_cog.get_queue(guild_id).append(
                {"url": fixtures[1], "title": "fixture-2", "requester": interaction.user}
            )
            vc.stop()
            ok = await wait_until(
                lambda: (music_cog.get_current_song(guild_id) or {}).get("title") == "fixture-2"
            )
            if not ok:
                raise AssertionError("skip 後 play_next 在時限內沒有切到下一首")
            step.passed = True
            step.detail = f"目前播放中: {music_cog.get_current_song(guild_id).get('title')!r}"
        except Exception as e:
            step.passed = False
            step.detail = f"{type(e).__name__}: {e}"
            traceback.print_exc()

    # --- Step 4: 推薦系統 ---
    step = StepResult("Recommend")
    results.append(step)
    if not results[0].passed:
        step.passed = None
        step.detail = "略過：Play 失敗"
    else:
        try:
            before_title = (music_cog.get_current_song(guild_id) or {}).get("title")
            music_cog.set_loop_mode(guild_id, LoopMode.RECOMMEND)
            vc.stop()  # 佇列是空的 -> 應該會流進 get_recommendation()
            ok = await wait_until(
                lambda: (music_cog.get_current_song(guild_id) or {}).get("title") != before_title,
                timeout=30,
            )
            if not ok:
                raise AssertionError("推薦模式在時限內沒有推薦出新歌並播放")
            step.passed = True
            step.detail = f"推薦並播放中: {music_cog.get_current_song(guild_id).get('title')!r}"
        except Exception as e:
            step.passed = False
            step.detail = f"{type(e).__name__}: {e}"
            traceback.print_exc()


async def main():
    token = os.getenv("DISCORD_TOKEN")
    guild_id_raw = os.getenv("VERIFY_GUILD_ID")
    channel_id_raw = os.getenv("VERIFY_VOICE_CHANNEL_ID")
    if not token or not guild_id_raw or not channel_id_raw:
        print("缺少 .env 中的 DISCORD_TOKEN / VERIFY_GUILD_ID / VERIFY_VOICE_CHANNEL_ID")
        sys.exit(1)
    guild_id = int(guild_id_raw)
    channel_id = int(channel_id_raw)

    fixtures_env = os.getenv("VERIFY_FIXTURE_URLS")
    fixtures = [u.strip() for u in fixtures_env.split(",")] if fixtures_env else DEFAULT_FIXTURES

    database.setup_database()

    intents = discord.Intents.default()
    intents.voice_states = True
    client = discord.Client(intents=intents)

    results = []
    state = {"music_cog": None, "interaction": None}

    @client.event
    async def on_ready():
        print(f"已登入: {client.user}")
        try:
            guild = client.get_guild(guild_id)
            if guild is None:
                raise RuntimeError(f"bot 不是伺服器 {guild_id} 的成員")
            channel = guild.get_channel(channel_id)
            if channel is None:
                raise RuntimeError(f"在伺服器 {guild_id} 裡找不到語音頻道 {channel_id}")

            music_cog = MusicCog(bot=client)
            requester = FixtureRequester(guild, client.user.id, client.user.mention)
            interaction = LiveInteraction(guild=guild, channel=channel, user=requester)
            state["music_cog"] = music_cog
            state["interaction"] = interaction

            print(f"加入語音頻道 {channel.name!r}...")
            await music_cog.ensure_voice_connection(channel)

            await run_scenario(music_cog, interaction, fixtures, results)
        except Exception as e:
            results.append(StepResult(f"FATAL setup error: {type(e).__name__}: {e}"))
            traceback.print_exc()
        finally:
            if state["music_cog"] is not None and state["interaction"] is not None:
                try:
                    await state["music_cog"].stop_and_leave(state["interaction"])
                except Exception:
                    traceback.print_exc()
            await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=180)
    except asyncio.TimeoutError:
        results.append(StepResult("FATAL: 等待 bot 登入/結束逾時"))
    except Exception as e:
        results.append(StepResult(f"FATAL: {type(e).__name__}: {e}"))
        traceback.print_exc()

    print("\n=== 驗證結果總覽 ===")
    all_passed = True
    for r in results:
        status = "PASS" if r.passed else ("SKIP" if r.passed is None else "FAIL")
        if r.passed is False:
            all_passed = False
        print(f"[{status}] {r.name} - {r.detail}")

    if not results:
        all_passed = False
        print("沒有任何結果紀錄 -- on_ready 大概沒有被觸發過（檢查 DISCORD_TOKEN）。")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Import/syntax sanity check (no real Discord connection needed)**

Run: `env -u PYTHONPATH python3 -c "import ast; ast.parse(open('scripts/verify_playback.py').read()); print('syntax OK')"`
Expected: `syntax OK`.

Run: `env -u PYTHONPATH python3 -c "
import sys
sys.path.insert(0, '.')
import importlib.util
spec = importlib.util.spec_from_file_location('verify_playback', 'scripts/verify_playback.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print('import OK, has main:', hasattr(mod, 'main'))
"`
Expected: `import OK, has main: True` (this only proves the imports/module-level code work against the real `cogs/music.py`/`views/player_view.py` — it does not exercise the live Discord/voice path).

- [ ] **Step 4: Manual live verification (requires real credentials — do this once to confirm the harness itself works)**

This step cannot be automated or done by an agent without real Discord credentials. Whoever executes this task must:
1. Add `VERIFY_GUILD_ID` and `VERIFY_VOICE_CHANNEL_ID` to `.env`, pointing at a real test server/voice channel the bot already has access to.
2. Run: `env -u PYTHONPATH python scripts/verify_playback.py`
3. Confirm all four steps (Play/Pause-Resume/Skip/Recommend) print `PASS` and the script exits 0.
4. As a negative-control sanity check, temporarily break something real (e.g. rename `~/.nvm/versions/node/*/bin/node` or edit `_NODE_PATH` to a bogus path) and re-run, confirming the Play step actually fails or prints the "falls back to 403-prone android_vr client" warning, then revert the change.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_playback.py CLAUDE.md
git commit -m "feat: add live playback smoke-test CLI (Layer B verification tooling)"
```

---

### Task 7: Document the new testing workflow in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Replace the stale "no test tooling" line and add a Testing section**

Find this line in the `## Commands` section:

```
There is no lint/test/build tooling configured in this repo (no linter config, no test suite, no CI). Verify changes by running the bot against a real Discord test server/bot token.
```

Replace it with:

```
There is no lint/build tooling or CI configured in this repo, but there is a two-layer playback verification suite (see `docs/superpowers/specs/2026-08-20-playback-verification-tooling-design.md`):

```bash
# Layer A: fast, offline logic tests (mocks discord.py/yt-dlp, no network, no token). Run this after every code change.
pip install -r requirements-dev.txt
env -u PYTHONPATH pytest tests/

# Layer B: live smoke test against a real Discord test server/voice channel and real yt-dlp/YouTube.
# Run this after upgrading yt-dlp/discord.py, or before trusting a fix that touches real playback.
# Requires VERIFY_GUILD_ID / VERIFY_VOICE_CHANNEL_ID in .env (see below).
env -u PYTHONPATH python scripts/verify_playback.py
```

Note: on machines with ROS2 sourced into the shell (`PYTHONPATH` containing `/opt/ros/...`), plain `pytest`/`python` invocations can fail with an unrelated `ModuleNotFoundError: No module named 'lark'` from pytest's plugin autoload picking up ROS's `launch_testing` package. The `env -u PYTHONPATH` prefix above works around it.
```

- [ ] **Step 2: Verify the doc renders sensibly**

Run: `cat CLAUDE.md` and visually confirm the new section reads correctly in context (no broken code fences, no duplicated content).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document the two-layer playback verification workflow"
```
