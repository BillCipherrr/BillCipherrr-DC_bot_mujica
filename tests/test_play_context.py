import asyncio
import dataclasses

import pytest
from conftest import FakeMember

import database
from mujica.context import PlayContext
from mujica.song import Song
from views.player_view import LoopMode, PlayerView


def test_from_interaction_copies_guild_channel_user(make_interaction):
    interaction = make_interaction()
    ctx = PlayContext.from_interaction(interaction)
    assert ctx.guild is interaction.guild
    assert ctx.channel is interaction.channel
    assert ctx.user is interaction.user


def test_play_context_is_immutable(make_interaction):
    ctx = PlayContext.from_interaction(make_interaction())
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.user = None


async def test_player_view_holds_ctx_not_interaction(music_cog, make_interaction, patch_ytdlp, temp_db):
    interaction = make_interaction()
    ctx = PlayContext.from_interaction(interaction)
    music_cog.get_queue(interaction.guild.id).append(
        Song(url="https://www.youtube.com/watch?v=aaa", title="Song A", requester=interaction.user)
    )
    patch_ytdlp(result={"url": "https://stream.example/a", "title": "Song A", "duration": 100})
    await music_cog.play_next(ctx)

    view = music_cog.get_player_view(interaction.guild.id)
    assert isinstance(view, PlayerView)
    assert view.ctx is ctx
    assert not hasattr(view, "interaction")


def _seed_history(guild_id, user_id, url, title, plays, played_at=1):
    for _ in range(plays):
        database.log_song_play(guild_id, user_id, {"url": url, "title": title, "duration": 90})
    conn = database.get_db_connection()
    conn.execute("UPDATE play_history SET played_at = ? WHERE user_id = ? AND guild_id = ?", (played_at, user_id, guild_id))
    conn.commit()
    conn.close()


async def test_recommendation_follows_ctx_user_not_current_song_requester(
    music_cog, make_interaction, patch_ytdlp, temp_db
):
    interaction = make_interaction()
    guild = interaction.guild
    guild_id = guild.id
    user_a = interaction.user  # 目前歌曲的點播者
    user_b = FakeMember(voice_channel=guild.voice_client.channel)  # 觸發這一輪播放的人
    user_b.guild = guild
    guild.add_member(user_b)
    ctx = PlayContext(guild=guild, channel=interaction.channel, user=user_b)

    # 兩個人各有一首「不在最近 20 首內」的個人歷史歌曲；A 的播放次數更多，
    # 所以如果推薦錯誤地以 A 為準，就會選到 A 的歌。
    _seed_history(guild_id, user_a.id, "https://www.youtube.com/watch?v=a_song", "A Song", plays=3)
    _seed_history(guild_id, user_b.id, "https://www.youtube.com/watch?v=b_song", "B Song", plays=2)
    for i in range(20):  # 把最近 20 首的去重視窗塞滿，避免 a_song/b_song 被去重排除
        database.log_song_play(
            guild_id, 555, {"url": f"https://www.youtube.com/watch?v=filler{i}", "title": f"Filler {i}", "duration": 60}
        )

    music_cog.set_loop_mode(guild_id, LoopMode.RECOMMEND)
    music_cog.set_current_song(
        guild_id, Song(url="https://www.youtube.com/watch?v=current", title="Current", requester=user_a)
    )
    patch_ytdlp(result={"title": "B Song", "url": "https://stream.example/b"})

    await music_cog.play_next(ctx)
    await asyncio.sleep(0.1)  # RECOMMEND 分支用 create_task 排程下一輪，要等真實時間

    played = music_cog.get_current_song(guild_id)
    assert played is not None
    assert played.url == "https://www.youtube.com/watch?v=b_song"
    assert played.rec_source == "user_history"
