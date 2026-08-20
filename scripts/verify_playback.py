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
