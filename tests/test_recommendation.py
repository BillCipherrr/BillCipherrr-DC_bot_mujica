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
