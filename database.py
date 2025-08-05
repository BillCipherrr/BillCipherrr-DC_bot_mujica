import sqlite3
import time
from typing import Optional

DB_PATH = './dc_bot.db'

def get_db_connection():
    """建立並返回資料庫連線。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def setup_database():
    """初始化資料庫，建立所需的資料表。"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 建立 songs 資料表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS songs (
            song_id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtube_url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            duration INTEGER NOT NULL
        )
    ''')

    # 建立 play_history 資料表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS play_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            song_id INTEGER NOT NULL,
            played_at TIMESTAMP NOT NULL,
            FOREIGN KEY (song_id) REFERENCES songs (song_id)
        )
    ''')

    conn.commit()
    conn.close()
    print("資料庫已成功設定。")

def log_song_play(guild_id: int, user_id: int, song_info: dict):
    """記錄一首歌的播放歷史。"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. 查找或插入歌曲
    cursor.execute("SELECT song_id FROM songs WHERE youtube_url = ?", (song_info['url'],))
    result = cursor.fetchone()
    
    if result:
        song_id = result['song_id']
    else:
        cursor.execute(
            "INSERT INTO songs (youtube_url, title, duration) VALUES (?, ?, ?)",
            (song_info['url'], song_info['title'], song_info['duration'])
        )
        song_id = cursor.lastrowid

    # 2. 插入播放紀錄
    cursor.execute(
        "INSERT INTO play_history (guild_id, user_id, song_id, played_at) VALUES (?, ?, ?, ?)",
        (guild_id, user_id, song_id, int(time.time()))
    )

    conn.commit()
    conn.close()

def get_user_history(user_id: int, limit: int = 10) -> list:
    """獲取指定使用者的播放歷史，並計算重複次數。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.title, s.youtube_url, MAX(h.played_at) as last_played, COUNT(h.song_id) as play_count
        FROM play_history h
        JOIN songs s ON h.song_id = s.song_id
        WHERE h.user_id = ?
        GROUP BY h.song_id
        ORDER BY last_played DESC
        LIMIT ?
    ''', (user_id, limit))
    history = cursor.fetchall()
    conn.close()
    return history

def get_server_history(guild_id: int, limit: int = 10) -> list:
    """獲取指定伺服器的播放歷史，並計算重複次數。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT s.title, s.youtube_url, h.user_id, MAX(h.played_at) as last_played, COUNT(h.song_id) as play_count
        FROM play_history h
        JOIN songs s ON h.song_id = s.song_id
        WHERE h.guild_id = ?
        GROUP BY h.song_id, h.user_id
        ORDER BY last_played DESC
        LIMIT ?
    ''', (guild_id, limit))
    history = cursor.fetchall()
    conn.close()
    return history