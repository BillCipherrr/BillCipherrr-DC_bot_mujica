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
