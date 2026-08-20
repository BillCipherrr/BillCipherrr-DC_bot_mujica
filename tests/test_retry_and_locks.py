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
