"""歌曲資料結構（不依賴 discord）。"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Song:
    """佇列中的一首歌，同時也是「目前播放中」的歌。

    欄位分三類：入列時就已知的、解析串流後才填入的、播放進度追蹤用的。
    """

    # --- 入列時已知 ---
    url: str
    title: str
    requester: Any  # discord.Member / discord.User；推薦歌曲則是 bot 自己
    rec_source: str | None = None  # 推薦來源：user_history / guild_top / youtube_api

    # --- 解析串流後才有（由 apply_stream_info 填入）---
    stream_url: str | None = None
    duration: int = 0
    thumbnail: str | None = None
    uploader: str = '未知作者'
    view_count: int = 0
    http_headers: dict = field(default_factory=dict)

    # --- 播放進度（以 time.time() 推算，不向 voice client 查詢）---
    start_time: float = 0.0
    resume_offset: float = 0.0
    paused_position: float | None = None

    def apply_stream_info(self, info: dict) -> None:
        """用 yt-dlp extract_info 的結果更新串流網址與詳細資訊。"""
        self.stream_url = info['url']
        self.title = info.get('title', self.title)  # 更新標題以防萬一
        self.duration = info.get('duration', 0)
        self.thumbnail = info.get('thumbnail')
        self.uploader = info.get('uploader', '未知作者')
        self.view_count = info.get('view_count', 0)
        self.http_headers = info.get('http_headers', {})
