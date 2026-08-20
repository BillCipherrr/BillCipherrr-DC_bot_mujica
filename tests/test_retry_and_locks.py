import asyncio

import discord
import pytest

import cogs.music as music_module
from conftest import FakeGuild, FakeVoiceChannel


async def test_concurrent_play_next_and_after_playing_dont_double_play(
    music_cog, make_interaction, patch_ytdlp, temp_db, monkeypatch
):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    queue = music_cog.get_queue(guild_id)
    queue.append({"url": "https://www.youtube.com/watch?v=aaa", "title": "Song A", "requester": interaction.user})
    queue.append({"url": "https://www.youtube.com/watch?v=bbb", "title": "Song B", "requester": interaction.user})

    patch_ytdlp(result={"url": "https://stream.example/x.m4a", "title": "Resolved", "duration": 100})

    # 模擬 play_lock 被加上去要修的那個確切競態：after_playing 的成功回呼
    # 重新進入 play_next()，同時又有別的東西也對同一個 guild 呼叫 play_next()。
    #
    # 直接斷言 play_calls/DB 寫入次數並不足以證明鎖真的有作用：
    # FakeVoiceClient.play() 是完全同步、內部沒有任何 await 的方法，所以就算
    # 沒有 play_lock，兩個呼叫也不可能真的同時執行到 play() 內部；第二次呼叫
    # 一樣會撞上「Already playing audio」的既有例外處理而讓 play_calls 穩定
    # 停在 1 —— 這件事跟鎖存不存在無關（已用移除鎖並連跑 5 次驗證過，一樣穩定
    # 通過）。真正能證明鎖有作用的，是直接量測「同一時間有幾個
    # _play_next_locked 呼叫真的在執行中」，也就是鎖保護的臨界區間本身。
    concurrent_count = 0
    max_concurrent = 0
    original_play_next_locked = music_cog._play_next_locked

    async def instrumented_play_next_locked(interaction_arg):
        nonlocal concurrent_count, max_concurrent
        concurrent_count += 1
        max_concurrent = max(max_concurrent, concurrent_count)
        try:
            await original_play_next_locked(interaction_arg)
        finally:
            concurrent_count -= 1

    monkeypatch.setattr(music_cog, "_play_next_locked", instrumented_play_next_locked)

    await asyncio.gather(
        music_cog.play_next(interaction),
        music_cog._handle_after_playing(interaction, guild_id, None),
    )

    # 這才是鎖真正保證的事：_play_next_locked 的執行區間永遠不會重疊。
    assert max_concurrent == 1

    vc = interaction.guild.voice_client
    # 下面兩個斷言記錄的是「鎖生效後」實際會發生的行為（先跑的那個播 Song A，
    # 第二個呼叫因為 voice client 還在 in-flight 狀態而被既有的
    # ClientException 處理擋下、安靜放棄），但如前述，這兩個斷言本身不足以
    # 單獨證明鎖的存在，所以搭配上面的 max_concurrent 斷言一起看。
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
