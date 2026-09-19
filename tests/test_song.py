from mujica.song import Song


def _song(**kw):
    return Song(url="https://www.youtube.com/watch?v=aaa", title="Queued Title", requester="someone", **kw)


def test_defaults_before_resolving():
    song = _song()
    assert song.stream_url is None
    assert song.duration == 0
    assert song.resume_offset == 0
    assert song.paused_position is None
    assert song.rec_source is None


def test_http_headers_default_is_not_shared_between_instances():
    a, b = _song(), _song()
    a.http_headers["X"] = "1"
    assert b.http_headers == {}


def test_apply_stream_info_fills_all_fields():
    song = _song()
    song.apply_stream_info({
        "url": "https://stream.example/a", "title": "Resolved Title", "duration": 120,
        "thumbnail": "https://img.example/a.jpg", "uploader": "Uploader", "view_count": 42,
        "http_headers": {"User-Agent": "UA"},
    })
    assert song.stream_url == "https://stream.example/a"
    assert song.title == "Resolved Title"
    assert song.duration == 120
    assert song.thumbnail == "https://img.example/a.jpg"
    assert song.uploader == "Uploader"
    assert song.view_count == 42
    assert song.http_headers == {"User-Agent": "UA"}


def test_apply_stream_info_keeps_queued_title_when_missing():
    song = _song()
    song.apply_stream_info({"url": "https://stream.example/a"})
    assert song.title == "Queued Title"
    assert song.uploader == "未知作者"
    assert song.duration == 0
