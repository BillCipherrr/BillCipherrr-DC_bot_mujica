from views.player_view import LoopMode


def test_guild_states_are_isolated(music_cog):
    music_cog.get_queue(1).append({"title": "A"})
    music_cog.set_loop_mode(1, LoopMode.SONG)
    music_cog.set_current_song(1, {"title": "A"})

    assert len(music_cog.get_queue(2)) == 0
    assert music_cog.get_loop_mode(2) == LoopMode.NONE
    assert music_cog.get_current_song(2) is None
    assert music_cog.get_state(1) is not music_cog.get_state(2)


def test_get_state_is_stable_per_guild(music_cog):
    assert music_cog.get_state(1) is music_cog.get_state(1)


def test_state_defaults(music_cog):
    state = music_cog.get_state(1)
    assert state.loop_mode == LoopMode.NONE
    assert state.volume == 0.5
    assert state.playlist_enabled is True
    assert state.consecutive_play_failures == 0


def test_playlist_toggle_is_per_guild(music_cog):
    music_cog.set_playlist_enabled(1, False)
    assert music_cog.is_playlist_enabled(1) is False
    assert music_cog.is_playlist_enabled(2) is True


def test_debug_mode_falls_back_to_global_default_then_overrides(music_cog):
    music_cog.global_debug_default = True
    assert music_cog.is_debug_enabled(1) is True  # 未設定 -> 沿用全域預設

    music_cog.set_debug_mode(1, False)
    assert music_cog.is_debug_enabled(1) is False  # 明確設定為 False 要能蓋過全域的 True
    assert music_cog.is_debug_enabled(2) is True  # 其他 guild 不受影響


async def test_session_summary_sends_once_and_clears_session_songs(music_cog, make_interaction):
    interaction = make_interaction()
    guild_id = interaction.guild.id
    music_cog.get_state(guild_id).session_songs.append(
        {"title": "Song A", "url": "https://www.youtube.com/watch?v=aaa", "requester": "someone"}
    )

    await music_cog._send_session_summary(interaction.channel, guild_id)
    assert len(interaction.channel.sent_messages) == 1
    assert music_cog.get_state(guild_id).session_songs == []

    await music_cog._send_session_summary(interaction.channel, guild_id)
    assert len(interaction.channel.sent_messages) == 1  # 已清空，不會重複送
