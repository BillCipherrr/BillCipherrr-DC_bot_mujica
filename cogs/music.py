import discord
from discord.ext import commands, tasks
from discord import app_commands
import yt_dlp
import os
import asyncio
import random
import time
import logging
import traceback
from collections import deque
from urllib.parse import urlparse, parse_qs, urlencode


# 匯入其他的 View
from views.player_view import PlayerView, LoopMode
from views.settings_view import SettingsView
import database

# 從環境變數讀取 API 金鑰
from googleapiclient.discovery import build
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    print("警告：未找到 YOUTUBE_API_KEY 環境變數，推薦功能將無法使用。")
    youtube = None
else:
    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    except Exception as e:
        print(f"初始化 YouTube API 時發生錯誤: {e}")
        youtube = None

# --- 正確的 yt-dlp 設定 ---

# 用於 /play 指令：快速提取資訊，允許播放列表
YDL_OPTS_INFO_EXTRACT = {
    'quiet': True,
    'extract_flat': True, 
    'noplaylist': False, # <-- 允許播放列表
}

# 用於 play_next 函式：獲取單一歌曲的串流，禁止播放列表
YDL_OPTS_STREAM = {
    'format': 'bestaudio/best',
    'quiet': True,
    'noplaylist': True, # <-- 禁止播放列表
    'source_address': '0.0.0.0'
}

# FFmpeg 選項
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

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

class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues = {}
        self.loop_modes = {}
        self.current_songs = {}
        self.player_messages = {}
        self.player_views = {}
        self.progress_tasks = {}
        self.volumes = {}
        self.disconnect_timers = {}
        self.playlist_enabled = {}
        self.logger = logging.getLogger(__name__)

    # --- 輔助函式 ---
    def get_queue(self, guild_id: int) -> deque: return self.queues.setdefault(guild_id, deque())
    def get_loop_mode(self, guild_id: int) -> LoopMode: return self.loop_modes.setdefault(guild_id, LoopMode.NONE)
    def set_loop_mode(self, guild_id: int, mode: LoopMode): self.loop_modes[guild_id] = mode
    def get_current_song(self, guild_id: int): return self.current_songs.get(guild_id)
    def set_current_song(self, guild_id: int, song_info): self.current_songs[guild_id] = song_info
    def get_player_message(self, guild_id: int): return self.player_messages.get(guild_id)
    def set_player_message(self, guild_id: int, message): self.player_messages[guild_id] = message
    def get_player_view(self, guild_id: int): return self.player_views.get(guild_id)
    def set_player_view(self, guild_id: int, view): self.player_views[guild_id] = view
    def get_volume(self, guild_id: int) -> float: return self.volumes.setdefault(guild_id, 0.5)
    def is_playlist_enabled(self, guild_id: int) -> bool: return self.playlist_enabled.setdefault(guild_id, True)

    def cancel_disconnect_timer(self, guild_id: int):
        if guild_id in self.disconnect_timers:
            self.disconnect_timers[guild_id].cancel()
            del self.disconnect_timers[guild_id]

    async def start_disconnect_timer(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        self.cancel_disconnect_timer(guild_id)
        async def disconnect_after_delay():
            await asyncio.sleep(300)
            voice_client = self.bot.get_guild(guild_id).voice_client
            if voice_client and not (voice_client.is_playing() or voice_client.is_paused()):
                await interaction.channel.send("閒置超過 5 分鐘，自動離開頻道。")
                await self.stop_and_leave(interaction)
        self.disconnect_timers[guild_id] = asyncio.create_task(disconnect_after_delay())

    def toggle_loop_mode(self, guild_id: int, mode: LoopMode):
        current_mode = self.get_loop_mode(guild_id)
        self.set_loop_mode(guild_id, LoopMode.NONE if current_mode == mode else mode)

    def get_current_position(self, guild_id: int) -> float:
        vc = self.bot.get_guild(guild_id).voice_client
        song = self.get_current_song(guild_id)
        if not vc or not vc.is_playing() or not song: return 0
        if vc.is_paused(): return song.get('paused_position', 0)
        return (time.time() - song.get('start_time', 0)) + song.get('resume_offset', 0)

    def start_progress_task(self, guild_id: int):
        if guild_id in self.progress_tasks and self.progress_tasks[guild_id].is_running(): return
        task = tasks.loop(seconds=10)(self.update_progress)
        self.progress_tasks[guild_id] = task
        task.start(guild_id)

    def stop_progress_task(self, guild_id: int):
        if guild_id in self.progress_tasks:
            self.progress_tasks[guild_id].cancel()
            del self.progress_tasks[guild_id]

    async def update_progress(self, guild_id: int):
        view = self.get_player_view(guild_id)
        if view:
            position = self.get_current_position(guild_id)
            await view.update_player(position)

    async def ensure_recommendation_seed(self, interaction: discord.Interaction):
        """When recommend mode is enabled and queue is empty, prefetch one recommendation so users can see it right away."""
        guild_id = interaction.guild.id
        if self.get_loop_mode(guild_id) != LoopMode.RECOMMEND: return
        queue = self.get_queue(guild_id)
        if queue: return
        current = self.get_current_song(guild_id)
        if not current: return
        try:
            rec = await self.get_recommendation(current, interaction.user)
            queue.append(rec)
            view = self.get_player_view(guild_id)
            if view: await view.update_player(self.get_current_position(guild_id))
        except Exception as e:
            self.logger.warning("ensure_recommendation_seed failed", exc_info=e)
            try:
                await interaction.followup.send(f"推薦歌曲時發生錯誤: {e}", ephemeral=True)
            except Exception:
                pass

    # --- 核心播放邏輯 (已修正) ---
    async def play_next(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        self.stop_progress_task(guild_id)
        voice_client = interaction.guild.voice_client
        queue = self.get_queue(guild_id)
        loop_mode = self.get_loop_mode(guild_id)
        current_song = self.get_current_song(guild_id)

        if current_song:
            if loop_mode == LoopMode.SONG: queue.appendleft(current_song)
            elif loop_mode == LoopMode.QUEUE: queue.append(current_song)

        if not queue:
            if loop_mode == LoopMode.RECOMMEND and current_song:
                await interaction.channel.send(f"🎶 佇列已空，正在為您推薦下一首歌...")
                try:
                    recommended_song_info = await self.get_recommendation(current_song, interaction.user)
                    queue.append(recommended_song_info)
                    asyncio.create_task(self.play_next(interaction))
                except Exception as e:
                    await interaction.channel.send(f"推薦歌曲時發生錯誤: {e}")
                return
            self.set_current_song(guild_id, None)
            player_message = self.get_player_message(guild_id)
            if player_message: await player_message.edit(content="播放佇列已結束。", embed=None, view=None)
            self.set_player_message(guild_id, None)
            await self.start_disconnect_timer(interaction)
            return

        if loop_mode == LoopMode.SHUFFLE and len(queue) > 1:
            next_song_index = random.randint(0, len(queue) - 1)
            next_song = queue.pop(next_song_index)
        else:
            next_song = queue.popleft()

        self.set_current_song(guild_id, next_song)

        try:
            loop = asyncio.get_event_loop()
            # 使用 YDL_OPTS_STREAM 獲取單一歌曲的串流 URL
            with yt_dlp.YoutubeDL(YDL_OPTS_STREAM) as ydl:
                song_data = await loop.run_in_executor(None, lambda: ydl.extract_info(next_song['url'], download=False))
            
            # 更新歌曲詳細資訊 (確保使用 'url' 鍵)
            next_song['stream_url'] = song_data['url']
            next_song['title'] = song_data.get('title', next_song.get('title', '未知歌曲')) # 更新標題以防萬一
            next_song['duration'] = song_data.get('duration', 0)
            next_song['thumbnail'] = song_data.get('thumbnail')
            next_song['uploader'] = song_data.get('uploader', '未知作者')
            next_song['view_count'] = song_data.get('view_count', 0)
            
            next_song['start_time'] = time.time()
            next_song['resume_offset'] = 0

            source = discord.FFmpegPCMAudio(next_song['stream_url'], **FFMPEG_OPTIONS)
            volume_source = discord.PCMVolumeTransformer(source, volume=self.get_volume(guild_id))
            
            def after_playing(error):
                if error: print(f'Player error: {error}')
                asyncio.run_coroutine_threadsafe(self.play_next(interaction), self.bot.loop)

            voice_client.play(volume_source, after=after_playing)

            database.log_song_play(guild_id, next_song['requester'].id, next_song)

            view = PlayerView(self, interaction)
            self.set_player_view(guild_id, view)
            embed = view.create_embed(next_song)
            player_message = self.get_player_message(guild_id)
            if player_message: await player_message.edit(content=None, embed=embed, view=view)
            else: 
                player_message = await interaction.channel.send(embed=embed, view=view)
                self.set_player_message(guild_id, player_message)
            self.start_progress_task(guild_id)

        except Exception as e:
            self.logger.error("play_next error for %s", next_song.get('title'), exc_info=e)
            await interaction.channel.send(f"播放 **{next_song['title']}** 時發生錯誤: {e}")
            asyncio.run_coroutine_threadsafe(self.play_next(interaction), self.bot.loop)

    # --- 推薦功能 ---
    async def get_recommendation(self, song_info: dict, requester: discord.User):
        if not youtube:
            raise Exception("YouTube API 未正確初始化，無法使用推薦功能。")

        video_id = extract_video_id(song_info.get('url', '') or song_info.get('webpage_url', ''))
        if not video_id:
            raise Exception("無法解析當前歌曲的 videoId。")

        loop = asyncio.get_event_loop()

        def run_search(params):
            return youtube.search().list(**params).execute()

        params_related = {
            'part': 'snippet',
            'type': 'video',
            'relatedToVideoId': video_id,
            'maxResults': 10,
            'videoCategoryId': '10',
            'order': 'relevance',
            'safeSearch': 'none'
        }

        # 部分舊版 google-api-python-client 可能不支援 relatedToVideoId，失敗時改用關鍵字搜尋回退。
        try:
            search_response = await loop.run_in_executor(None, lambda: run_search(params_related))
        except TypeError:
            fallback_query = song_info.get('title') or song_info.get('uploader') or ''
            params_fallback = {
                'part': 'snippet',
                'type': 'video',
                'q': fallback_query,
                'maxResults': 10,
                'videoCategoryId': '10',
                'order': 'relevance',
                'safeSearch': 'none'
            }
            search_response = await loop.run_in_executor(None, lambda: run_search(params_fallback))

        played_ids = {
            extract_video_id(s.get('url', '') or s.get('webpage_url', ''))
            for s in self.get_queue(requester.guild.id)
        }
        current = self.get_current_song(requester.guild.id)
        if current:
            played_ids.add(extract_video_id(current.get('url', '') or current.get('webpage_url', '')))

        # 累積最近播過的歌曲 (含重新上傳的可能) 以避免推薦重複
        recent_rows = database.get_recent_songs(requester.guild.id, limit=20)
        played_ids.update(extract_video_id(r['youtube_url']) for r in recent_rows if r)
        played_titles = {normalize_title_for_dedup(r['title']) for r in recent_rows if r and r['title']}

        def to_video_id(item):
            return item['id']['videoId']

        candidates = []
        for item in search_response.get('items', []):
            vid = to_video_id(item)
            title_norm = normalize_title_for_dedup(item['snippet']['title'])
            if vid in played_ids: continue
            if title_norm in played_titles: continue
            candidates.append(item)
        if not candidates:
            raise Exception("找不到可推薦的歌曲。")

        chosen = candidates[0]  # 取最相關的第一首（若想要隨機，可改為 random.choice(candidates[:3]))
        vid = to_video_id(chosen)
        return {
            'url': f"https://www.youtube.com/watch?v={vid}",
            'title': chosen['snippet']['title'],
            'requester': self.bot.user
        }

    # --- /play 指令 (已修正) ---
    @app_commands.command(name="play", description="播放歌曲或播放列表")
    async def play(self, interaction: discord.Interaction, url: str):
        if not interaction.user.voice:
            return await interaction.response.send_message("您需要先加入一個語音頻道！", ephemeral=True)
        
        await interaction.response.defer()
        voice_client = interaction.guild.voice_client or await interaction.user.voice.channel.connect()
        
        try:
            # 使用 YDL_OPTS_INFO_EXTRACT 快速掃描，允許播放列表
            with yt_dlp.YoutubeDL(YDL_OPTS_INFO_EXTRACT) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ydl.extract_info(url, download=False)
                )

            queue = self.get_queue(interaction.guild.id)
            is_playing = voice_client.is_playing() or voice_client.is_paused()

            if 'entries' in info: 
                if not self.is_playlist_enabled(interaction.guild.id):
                    return await interaction.followup.send("❌ 此伺服器目前不允許播放列表。請聯絡管理員使用 `/settings` 來啟用。", ephemeral=True)
                
                entries = info['entries']
                await interaction.followup.send(f"✅ 已將播放列表 **{info['title']}** ({len(entries)} 首歌) 加入佇列。")
                for entry in entries:
                    if not entry: continue
                    entry_url = entry.get('webpage_url') or entry.get('url')
                    if entry_url and not entry_url.startswith('http'):
                        entry_url = f"https://www.youtube.com/watch?v={entry_url}"
                    entry_url = normalize_youtube_url(entry_url) if entry_url else None
                    queue.append({
                        'url': entry_url,
                        'title': entry.get('title', '未知歌曲'),
                        'requester': interaction.user
                    })
            else:
                song_info = {
                    'url': info.get('webpage_url', normalize_youtube_url(url)), 
                    'title': info.get('title', '未知歌曲'), 
                    'requester': interaction.user
                }
                queue.append(song_info)
                await interaction.followup.send(f"✅ 已將 **{song_info['title']}** 加入佇列。")
            
            if not is_playing:
                self.cancel_disconnect_timer(interaction.guild.id)
                await self.play_next(interaction)
            else:
                view = self.get_player_view(interaction.guild.id)
                if view: await view.update_player(self.get_current_position(interaction.guild.id))

        except Exception as e:
            self.logger.error("play command error", exc_info=e)
            await interaction.followup.send(f"處理歌曲時發生錯誤: {e}")

    # --- 其他指令 ---
    async def stop_and_leave(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        self.cancel_disconnect_timer(guild_id)
        self.stop_progress_task(guild_id)
        voice_client = interaction.guild.voice_client
        if voice_client:
            self.get_queue(guild_id).clear()
            self.set_current_song(guild_id, None)
            self.set_loop_mode(guild_id, LoopMode.NONE)
            if voice_client.is_playing() or voice_client.is_paused(): voice_client.stop()
            await voice_client.disconnect()
            player_message = self.get_player_message(guild_id)
            if player_message: 
                try: await player_message.delete()
                except discord.NotFound: pass
            self.set_player_message(guild_id, None)

    @app_commands.command(name="leave", description="讓機器人離開語音頻道並清空佇列")
    async def leave(self, interaction: discord.Interaction):
        await self.stop_and_leave(interaction)
        await interaction.response.send_message("👋 已離開頻道並清空佇列。")

    @app_commands.command(name="settings", description="[管理員] 開啟機器人設定面板")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction):
        view = SettingsView(self, interaction.guild.id)
        await interaction.response.send_message("⚙️ 機器人設定面板", view=view, ephemeral=True)

    @settings.error
    async def settings_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ 您需要擁有「管理伺服器」的權限才能使用此指令。", ephemeral=True)
        else:
            await interaction.response.send_message(f"發生未知錯誤: {error}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
