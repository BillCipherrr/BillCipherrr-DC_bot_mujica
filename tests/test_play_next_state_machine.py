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
