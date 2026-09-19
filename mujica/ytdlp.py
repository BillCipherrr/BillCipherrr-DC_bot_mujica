"""yt-dlp / FFmpeg 相關設定與輔助函式（不依賴 discord）。"""
import glob
import os
import shlex
import shutil

# --- 正確的 yt-dlp 設定 ---

# 系統本身沒有安裝 deno（yt-dlp 預設唯一啟用的 JS runtime），但已有 node（經 nvm 安裝，
# 版本 >= 20 符合 yt-dlp 需求），因此改用 node 讓 yt-dlp 能解密簽章、嘗試 web/web safari
# 等 client，而不是只能退回較弱、容易被 403 的 android_vr client。
#
# yt-dlp 只用字面上的 "node" 去 PATH 找執行檔；但 bot 長時間執行的行程（例如透過
# nohup/screen/tmux/systemd 啟動）未必繼承有把 nvm 的 node 目錄加進 PATH 的互動式
# shell 環境，一旦找不到 node 就會靜默退回 JS-less 的 android_vr client，導致串流
# URL 經常被 YouTube 回 403。因此在載入模組時就把 node 解析成絕對路徑寫死，
# 不依賴執行當下的 PATH。
#
# 注意：這台機器 /usr/bin/node 是系統套件裝的舊版 (v12)，低於 yt-dlp 要求的
# >= 20，若單純用 shutil.which('node')，只要 PATH 沒把 nvm 目錄排在 /usr/bin
# 前面，就會撿到這個版本過舊、會被 yt-dlp 判定為不支援的 node，症狀跟完全找
# 不到 node 一樣（一樣印出 "No supported JavaScript runtime"）。因此優先找
# nvm 安裝的版本，找不到才退回 PATH 查找。
def _resolve_node_path() -> str | None:
    nvm_candidates = sorted(
        glob.glob(os.path.expanduser('~/.nvm/versions/node/*/bin/node')),
        reverse=True,  # 取版本號較新的
    )
    if nvm_candidates:
        return nvm_candidates[0]
    return shutil.which('node')

_NODE_PATH = _resolve_node_path()
YDL_JS_RUNTIMES = {'node': {'path': _NODE_PATH}} if _NODE_PATH else {}
if not _NODE_PATH:
    print("警告：找不到 node 執行檔，yt-dlp 將退回 JS-less 的 android_vr client，串流較容易遇到 403。")

# 用於 /play 指令：快速提取資訊，允許播放列表
YDL_OPTS_INFO_EXTRACT = {
    'quiet': True,
    'extract_flat': True,
    'noplaylist': False, # <-- 允許播放列表
    'js_runtimes': YDL_JS_RUNTIMES,
}

# 用於 play_next 函式：獲取單一歌曲的串流，禁止播放列表
YDL_OPTS_STREAM = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True, # <-- 禁止播放列表
    'source_address': '0.0.0.0',
    'socket_timeout': 10,  # 避免來源被節流/擋下時 extract_info 無限期卡住，拖住 per-guild play_lock
    'retries': 2,
    'js_runtimes': YDL_JS_RUNTIMES,
}

# 允許透過環境變數提供 cookies，處理需登入/受限資源（例如部份 Google Drive 連結）
YTDLP_COOKIEFILE = os.getenv("YTDLP_COOKIEFILE")
if YTDLP_COOKIEFILE:
    YDL_OPTS_STREAM['cookiefile'] = YTDLP_COOKIEFILE

# FFmpeg 選項
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}


def build_ffmpeg_options(song_data: dict) -> dict:
    """根據 yt-dlp 回傳的 http_headers 建立 ffmpeg 參數，降低 403 機率。"""
    opts = dict(FFMPEG_OPTIONS)
    before = opts.get('before_options', '')
    extra_parts = [
        '-reconnect_at_eof 1',
        '-reconnect_on_http_error 4xx,5xx',
    ]

    headers = song_data.get('http_headers') or {}
    user_agent = headers.get('User-Agent') or headers.get('user-agent')
    if user_agent:
        extra_parts.append(f"-user_agent {shlex.quote(str(user_agent))}")

    header_lines = []
    for k, v in headers.items():
        if not v:
            continue
        lk = k.lower()
        if lk in ('user-agent', 'accept-encoding'):
            continue
        header_lines.append(f"{k}: {v}")

    if header_lines:
        escaped_headers = '\\r\\n'.join(header_lines) + '\\r\\n'
        extra_parts.append(f"-headers {shlex.quote(escaped_headers)}")

    merged_before = ' '.join(part for part in [before.strip(), ' '.join(extra_parts).strip()] if part).strip()
    opts['before_options'] = merged_before
    return opts
