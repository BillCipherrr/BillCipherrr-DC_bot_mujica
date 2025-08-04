import discord
from discord.ext import commands, tasks
from discord import app_commands
import yt_dlp
import os
import asyncio
import random
import time
from collections import deque
from views.player_view import PlayerView, LoopMode

# --- 設定 ---
DOWNLOADS_DIR = './downloads'
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': os.path.join(DOWNLOADS_DIR, '%(title)s.%(ext)s'),
    'noplaylist': True, 'quiet': True, 'extract_flat': 'in_playlist',
    'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
    'restrictfilenames': True,
}
FFMPEG_OPTIONS = {'options': '-vn'}

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

    # --- Helper Functions (維持不變) ---
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

    def toggle_loop_mode(self, guild_id: int, mode: LoopMode):
        current_mode = self.get_loop_mode(guild_id)
        self.set_loop_mode(guild_id, LoopMode.NONE if current_mode == mode else mode)

    def cleanup_file(self, filepath):
        if filepath and os.path.exists(filepath):
            try: os.remove(filepath)
            except OSError as e: print(f"Error removing file {filepath}: {e}")

    def get_current_position(self, guild_id: int) -> float:
        vc = self.bot.get_guild(guild_id).voice_client
        song = self.get_current_song(guild_id)
        if not vc or not vc.is_playing() or not song: return 0
        if vc.is_paused(): return song.get('paused_position', 0)
        return (time.time() - song.get('start_time', 0)) + song.get('resume_offset', 0)

    async def download_song(self, url: str):
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            filepath = ydl.prepare_filename(info)
            if info.get('_type') == 'playlist': info = info['entries'][0]
            base, _ = os.path.splitext(filepath)
            filepath = base + '.mp3'
            return {
                'url': info.get('webpage_url'), 'title': info.get('title', '未知歌曲'),
                'filepath': filepath, 'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration', 0), 'uploader': info.get('uploader', '未知作者'),
                'view_count': info.get('view_count', 0)
            }

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
            self.set_current_song(guild_id, None)
            player_message = self.get_player_message(guild_id)
            if player_message: await player_message.edit(content="播放佇列已結束。", embed=None, view=None)
            self.set_player_message(guild_id, None)
            return

        if loop_mode == LoopMode.SHUFFLE and len(queue) > 1:
            next_song_index = random.randint(0, len(queue) - 1)
            next_song = queue.pop(next_song_index)
        else:
            next_song = queue.popleft()

        if not next_song.get('filepath') or not os.path.exists(next_song.get('filepath')):
            try:
                download_msg = await interaction.channel.send(f"📥 正在下載: **{next_song['title']}**")
                downloaded_info = await self.download_song(next_song['url'])
                next_song.update(downloaded_info)
                await download_msg.delete()
            except Exception as e:
                await interaction.channel.send(f"下載 **{next_song['title']}** 時失敗: {e}")
                asyncio.run_coroutine_threadsafe(self.play_next(interaction), self.bot.loop)
                return

        self.set_current_song(guild_id, next_song)
        next_song['start_time'] = time.time()
        next_song['resume_offset'] = 0

        try:
            def after_playing(error):
                if error: print(f'Player error: {error}')
                self.cleanup_file(next_song['filepath'])
                asyncio.run_coroutine_threadsafe(self.play_next(interaction), self.bot.loop)

            source = discord.FFmpegPCMAudio(next_song['filepath'], **FFMPEG_OPTIONS)
            volume_source = discord.PCMVolumeTransformer(source, volume=self.get_volume(guild_id))
            voice_client.play(volume_source, after=after_playing)

            view = PlayerView(self, interaction)
            self.set_player_view(guild_id, view)
            embed = view.create_embed(next_song)
            player_message = self.get_player_message(guild_id)
            if player_message: await player_message.edit(content=None, embed=embed, view=view)
            else: 
                player_message = await interaction.channel.send(embed=embed, view=view)
                self.set_player_message(guild_id, player_message)
            self.start_progress_task(guild_id)
        except Exception as e: await interaction.channel.send(f"播放時發生錯誤: {e}")

    @app_commands.command(name="play", description="播放歌曲或播放列表")
    async def play(self, interaction: discord.Interaction, url: str):
        if not interaction.user.voice: return await interaction.response.send_message("您需要先加入一個語音頻道！", ephemeral=True)
        await interaction.response.defer()
        voice_client = interaction.guild.voice_client or await interaction.user.voice.channel.connect()
        try:
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            queue = self.get_queue(interaction.guild.id)
            is_playing = voice_client.is_playing() or voice_client.is_paused()

            if info.get('_type') == 'playlist':
                entries = info.get('entries', [])
                await interaction.followup.send(f"✅ 已將播放列表 **{info['title']}** ({len(entries)} 首歌) 加入佇列。")
                for entry in entries:
                    queue.append({'url': entry.get('webpage_url'), 'title': entry.get('title', '未知歌曲'), 'duration': entry.get('duration', 0), 'requester': interaction.user})
            else:
                song_info = {'url': info.get('webpage_url'), 'title': info.get('title', '未知歌曲'), 'duration': info.get('duration', 0), 'requester': interaction.user}
                queue.append(song_info)
                await interaction.followup.send(f"✅ 已將 **{song_info['title']}** 加入佇列。")
            
            if not is_playing:
                await self.play_next(interaction)
            else:
                # --- 核心修改：如果正在播放，則更新播放器介面 ---
                view = self.get_player_view(interaction.guild.id)
                if view:
                    await view.update_player(self.get_current_position(interaction.guild.id))

        except Exception as e: await interaction.followup.send(f"處理歌曲時發生錯誤: {e}")

    # --- 移除 /queue 指令 ---
    # (此指令的功能已被整合到播放器中)

    async def stop_and_leave(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        self.stop_progress_task(guild_id)
        voice_client = interaction.guild.voice_client
        if voice_client:
            self.get_queue(guild_id).clear()
            self.set_current_song(guild_id, None)
            self.set_loop_mode(guild_id, LoopMode.NONE)
            if voice_client.is_playing() or voice_client.is_paused(): voice_client.stop()
            await voice_client.disconnect()
            player_message = self.get_player_message(guild_id)
            if player_message: await player_message.delete()
            self.set_player_message(guild_id, None)

    @app_commands.command(name="leave", description="讓機器人離開語音頻道並清空佇列")
    async def leave(self, interaction: discord.Interaction):
        await self.stop_and_leave(interaction)
        await interaction.response.send_message("👋 已離開頻道並清空佇列。")

async def setup(bot: commands.Bot):
    if not os.path.exists(DOWNLOADS_DIR): os.makedirs(DOWNLOADS_DIR)
    await bot.add_cog(MusicCog(bot))