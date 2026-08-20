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
