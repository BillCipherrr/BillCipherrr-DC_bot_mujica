import asyncio

from mujica.context import PlayContext
from mujica.song import Song
from views.player_view import PlayerView


async def test_pause_resume_position_tracking(music_cog, make_interaction, patch_ytdlp, temp_db):
    interaction = make_interaction()
    ctx = PlayContext.from_interaction(interaction)
    guild_id = interaction.guild.id
    queue = music_cog.get_queue(guild_id)
    queue.append(Song(url="https://www.youtube.com/watch?v=aaa", title="Song A", requester=interaction.user))
    patch_ytdlp(result={"url": "https://stream.example/a.m4a", "title": "Song A", "duration": 100})
    await music_cog.play_next(ctx)

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
    ctx = PlayContext.from_interaction(interaction)
    guild_id = interaction.guild.id
    queue = music_cog.get_queue(guild_id)
    queue.append(Song(url="https://www.youtube.com/watch?v=aaa", title="Song A", requester=interaction.user))
    patch_ytdlp(result={"title": "Song A", "url": "https://stream.example/a"})
    await music_cog.play_next(ctx)

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


async def test_skip_button_noop_when_nothing_playing(music_cog, make_interaction, monkeypatch):
    interaction = make_interaction()
    ctx = PlayContext.from_interaction(interaction)
    view = PlayerView(music_cog, ctx)
    vc = interaction.guild.voice_client
    assert not vc.is_playing() and not vc.is_paused()

    # vc.play_calls == 0 本身不足以證明 skip 真的沒動作：這個測試從頭到尾都
    # 沒呼叫過 play()，所以這個數字不管 skip_button 的 guard 有沒有被拿掉都
    # 會是 0。真正要驗證的是 vc.stop() 有沒有被呼叫，所以改成用 monkeypatch
    # 直接 spy 住它。
    stop_calls = []
    original_stop = vc.stop

    def spy_stop():
        stop_calls.append(True)
        return original_stop()

    monkeypatch.setattr(vc, "stop", spy_stop)

    await view.skip_button.callback(interaction)

    assert stop_calls == []  # skip 應該完全不呼叫 vc.stop()，因為沒有東西在播放/暫停
    assert vc.play_calls == 0
    assert interaction.response.sent


async def test_paused_position_zero_is_honored_not_treated_as_missing(
    music_cog, make_interaction, patch_ytdlp, temp_db
):
    interaction = make_interaction()
    ctx = PlayContext.from_interaction(interaction)
    guild_id = interaction.guild.id
    music_cog.get_queue(guild_id).append(
        Song(url="https://www.youtube.com/watch?v=aaa", title="Song A", requester=interaction.user)
    )
    patch_ytdlp(result={"url": "https://stream.example/a.m4a", "title": "Song A", "duration": 100})
    await music_cog.play_next(ctx)
    interaction.guild.voice_client.pause()

    song = music_cog.get_current_song(guild_id)
    song.resume_offset = 50
    song.paused_position = 0.0
    assert music_cog.get_current_position(guild_id) == 0.0  # 明確的 0 不能被當成「沒設定」而退回 resume_offset

    song.paused_position = None
    assert music_cog.get_current_position(guild_id) == 50  # 沒設定才退回 resume_offset
