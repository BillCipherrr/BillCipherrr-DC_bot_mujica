import cogs.music as music_module


def test_resolve_node_path_prefers_newest_nvm_version(monkeypatch):
    monkeypatch.setattr(
        music_module.glob,
        "glob",
        lambda pattern: [
            "/home/user/.nvm/versions/node/v18.20.0/bin/node",
            "/home/user/.nvm/versions/node/v20.11.0/bin/node",
        ],
    )
    monkeypatch.setattr(music_module.shutil, "which", lambda name: "/usr/bin/node")

    assert music_module._resolve_node_path() == "/home/user/.nvm/versions/node/v20.11.0/bin/node"


def test_resolve_node_path_falls_back_to_path_when_no_nvm(monkeypatch):
    monkeypatch.setattr(music_module.glob, "glob", lambda pattern: [])
    monkeypatch.setattr(music_module.shutil, "which", lambda name: "/usr/bin/node")

    assert music_module._resolve_node_path() == "/usr/bin/node"


def test_resolve_node_path_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr(music_module.glob, "glob", lambda pattern: [])
    monkeypatch.setattr(music_module.shutil, "which", lambda name: None)

    assert music_module._resolve_node_path() is None


def test_build_ffmpeg_options_injects_user_agent_and_headers():
    song = {
        "http_headers": {
            "User-Agent": "Mozilla/5.0 Test",
            "Referer": "https://example.com",
            "Accept-Encoding": "gzip",  # 必須被排除在 -headers 區塊之外
        }
    }
    opts = music_module.build_ffmpeg_options(song)
    assert "-user_agent" in opts["before_options"]
    assert "Mozilla/5.0 Test" in opts["before_options"]
    assert "Referer: https://example.com" in opts["before_options"]
    assert "Accept-Encoding" not in opts["before_options"].split("-headers")[-1]
    assert "-reconnect_on_http_error 4xx,5xx" in opts["before_options"]


def test_build_ffmpeg_options_no_headers_leaves_base_options_intact():
    opts = music_module.build_ffmpeg_options({})
    assert "-user_agent" not in opts["before_options"]
    assert opts["before_options"].startswith("-reconnect 1 -reconnect_streamed 1")


def test_normalize_youtube_url_expands_short_link():
    assert (
        music_module.normalize_youtube_url("https://youtu.be/abc123?t=5")
        == "https://www.youtube.com/watch?v=abc123?t=5"
    )


def test_extract_video_id_from_standard_url():
    assert music_module.extract_video_id("https://www.youtube.com/watch?v=abc123&list=xyz") == "abc123"


def test_extract_video_id_from_short_url():
    assert music_module.extract_video_id("https://youtu.be/abc123") == "abc123"


def test_normalize_title_for_dedup_strips_punctuation_and_case():
    assert music_module.normalize_title_for_dedup(
        "  Song Title!! (Official MV) "
    ) == music_module.normalize_title_for_dedup("song title official mv")
