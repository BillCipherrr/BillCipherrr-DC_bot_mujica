"""每個 guild 的播放狀態（不依賴 discord，方便測試與重設）。"""
import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mujica.song import Song


class LoopMode(Enum):
    NONE = 0
    SONG = 1
    QUEUE = 2
    SHUFFLE = 3
    RECOMMEND = 4


@dataclass
class GuildState:
    """單一 guild 的所有播放相關狀態。全部存在記憶體，重啟即消失。"""

    queue: deque[Song] = field(default_factory=deque)
    loop_mode: LoopMode = LoopMode.NONE
    current_song: Song | None = None
    volume: float = 0.5
    playlist_enabled: bool = True
    # None 表示沿用全域預設（MUSIC_DEBUG 環境變數）
    debug_mode: bool | None = None

    # 播放器 UI（discord.Message / PlayerView / tasks.Loop）
    player_message: Any = None
    player_view: Any = None
    progress_task: Any = None

    # 閒置 5 分鐘自動離開的計時器（asyncio.Task）
    disconnect_timer: Any = None

    # per-guild 語音連線鎖，防止競態
    voice_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # per-guild play_next 鎖，防止 after_playing 回呼與例外重試互相搶跑
    play_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # 連續播放失敗次數，避免無限重試風暴
    consecutive_play_failures: int = 0
    # 本次 session 播放過的歌曲（用於結束時的摘要）
    session_songs: list[Song] = field(default_factory=list)
