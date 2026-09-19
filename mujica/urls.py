"""URL 與標題的純函式工具。"""
from urllib.parse import parse_qs, urlparse


def normalize_youtube_url(url: str) -> str:
    # 解析網址
    parsed = urlparse(url)
    # 檢查是否為 youtu.be 短網址
    if parsed.netloc in ["youtu.be"]:
        video_id = parsed.path.lstrip("/")
        query = f"?{parsed.query}" if parsed.query else ""
        return f"https://www.youtube.com/watch?v={video_id}{query}"
    # 檢查是否為 youtube.com 並有 videoId
    if parsed.netloc in ["www.youtube.com", "youtube.com"]:
        # 已是標準格式，直接回傳
        return url
    return url


def extract_video_id(url: str):
    parsed = urlparse(url)
    if parsed.netloc in ("youtu.be", "www.youtu.be"):
        return parsed.path.lstrip("/")
    if parsed.netloc.endswith("youtube.com"):
        qs = parse_qs(parsed.query)
        return qs.get("v", [None])[0]
    return None


def normalize_title_for_dedup(title: str) -> str:
    cleaned = ''.join(ch for ch in title.lower() if ch.isalnum() or ch.isspace())
    return ' '.join(cleaned.split())
