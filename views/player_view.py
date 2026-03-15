import discord
import time
import random
from enum import Enum

# 定義播放模式的 Enum
class LoopMode(Enum):
    NONE = 0
    SONG = 1
    QUEUE = 2
    SHUFFLE = 3
    RECOMMEND = 4

class PlayerView(discord.ui.View):
    def __init__(self, music_cog, interaction):
        super().__init__(timeout=None)
        self.music_cog = music_cog
        self.interaction = interaction
        self.update_buttons()

    def update_buttons(self):
        guild_id = self.interaction.guild.id
        mode = self.music_cog.get_loop_mode(guild_id)
        vc = self.interaction.guild.voice_client

        if vc and vc.is_paused():
            self.pause_resume_button.label = "Play"
            self.pause_resume_button.emoji = "▶️"
            self.pause_resume_button.style = discord.ButtonStyle.success
        else:
            self.pause_resume_button.label = "Pause"
            self.pause_resume_button.emoji = "⏸️"
            self.pause_resume_button.style = discord.ButtonStyle.secondary

        self.loop_one_button.style = discord.ButtonStyle.secondary
        self.loop_queue_button.style = discord.ButtonStyle.secondary
        self.shuffle_button.style = discord.ButtonStyle.secondary
        if mode == LoopMode.SONG: self.loop_one_button.style = discord.ButtonStyle.primary
        elif mode == LoopMode.QUEUE: self.loop_queue_button.style = discord.ButtonStyle.primary
        elif mode == LoopMode.SHUFFLE: self.shuffle_button.style = discord.ButtonStyle.primary
        elif mode == LoopMode.RECOMMEND: self.recommend_button.style = discord.ButtonStyle.primary

    def create_progress_bar(self, current, total):
        if total == 0: return "--:-- / --:--", "`[--------------------]`"
        current_str = f"{int(current // 60):02d}:{int(current % 60):02d}"
        total_str = f"{int(total // 60):02d}:{int(total % 60):02d}"
        percentage = int((current / total) * 20) if total > 0 else 0
        bar = '─' * percentage + '🔘' + '─' * (20 - percentage)
        return f"{current_str} / {total_str}", f"`[{bar}]`"

    def create_embed(self, song_info, current_position=0):
        title = song_info.get('title', '未知歌曲')
        url = song_info.get('url', '#')
        thumbnail = song_info.get('thumbnail', None)
        requester = song_info.get('requester', '未知')
        duration = song_info.get('duration', 0)
        uploader = song_info.get('uploader', '未知作者')
        view_count = song_info.get('view_count', 0)

        embed = discord.Embed(title=title, url=url, color=discord.Color.green())
        if thumbnail: embed.set_image(url=thumbnail)
        embed.set_author(name=uploader)
        embed.add_field(name="點播者", value=requester.mention, inline=True)
        embed.add_field(name="觀看次數", value=f"{view_count:,}", inline=True)
        time_str, bar_str = self.create_progress_bar(current_position, duration)
        embed.add_field(name="\n進度", value=f"{bar_str}\n{time_str}", inline=False)

        # --- 核心修改：加入待播清單欄位 ---
        queue = self.music_cog.get_queue(self.interaction.guild.id)
        if queue:
            queue_list = ""
            for i, song in enumerate(list(queue)[:5]): # 最多顯示 5 首
                queue_list += f"`{i+1}.` {song['title']}\n"
            if len(queue) > 5:
                queue_list += f"\n...還有 {len(queue) - 5} 首歌"
            embed.add_field(name="🎶 待播清單", value=queue_list, inline=False)
        # ----------------------------------

        mode = self.music_cog.get_loop_mode(self.interaction.guild.id)
        embed.set_footer(text=f"播放模式: {mode.name}")
        return embed

    async def update_player(self, current_position=0):
        guild_id = self.interaction.guild.id
        player_message = self.music_cog.get_player_message(guild_id)
        current_song = self.music_cog.get_current_song(guild_id)
        if not player_message or not current_song: return

        self.update_buttons()
        embed = self.create_embed(current_song, current_position)
        try:
            await player_message.edit(embed=embed, view=self)
        except discord.HTTPException as e:
            print(f"編輯播放器訊息失敗: {e}")
            self.music_cog.stop_progress_task(guild_id)

    # --- 按鈕定義 (維持不變) ---
    @discord.ui.button(emoji="⏯️", label="Pause", style=discord.ButtonStyle.secondary)
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        guild_id = interaction.guild.id
        current_song = self.music_cog.get_current_song(guild_id)

        if vc and vc.is_playing():
            if current_song:
                current_song['paused_position'] = self.music_cog.get_current_position(guild_id)
                self.music_cog.debug_log(guild_id, "pause pressed at position=%.2f", current_song['paused_position'])
            vc.pause()
            await self.music_cog.start_disconnect_timer(interaction)
        elif vc and vc.is_paused():
            if current_song:
                paused_position = current_song.get('paused_position', current_song.get('resume_offset', 0))
                current_song['resume_offset'] = paused_position
                current_song['start_time'] = time.time()
                current_song.pop('paused_position', None)
                self.music_cog.debug_log(guild_id, "resume pressed from position=%.2f", paused_position)
            vc.resume()
            self.music_cog.cancel_disconnect_timer(guild_id)

        await self.update_player(self.music_cog.get_current_position(guild_id))
        await interaction.response.defer()

    @discord.ui.button(emoji="⏭️", label="Skip", style=discord.ButtonStyle.secondary)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()): vc.stop()
        await interaction.response.send_message("⏭️ 已跳過", ephemeral=True)

    @discord.ui.button(emoji="🔁", label="Loop Song", style=discord.ButtonStyle.secondary)
    async def loop_one_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.music_cog.toggle_loop_mode(interaction.guild.id, LoopMode.SONG)
        await self.update_player(self.music_cog.get_current_position(interaction.guild.id))
        await interaction.response.defer()

    @discord.ui.button(emoji="🔂", label="Loop Queue", style=discord.ButtonStyle.secondary)
    async def loop_queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.music_cog.toggle_loop_mode(interaction.guild.id, LoopMode.QUEUE)
        await self.update_player(self.music_cog.get_current_position(interaction.guild.id))
        await interaction.response.defer()

    @discord.ui.button(emoji="🔀", label="Shuffle", style=discord.ButtonStyle.secondary)
    async def shuffle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        guild_id = interaction.guild.id
        self.music_cog.toggle_loop_mode(guild_id, LoopMode.SHUFFLE)

        if self.music_cog.get_loop_mode(guild_id) == LoopMode.SHUFFLE:
            queue = self.music_cog.get_queue(guild_id)
            if len(queue) > 1:
                shuffled = list(queue)
                random.shuffle(shuffled)
                queue.clear()
                queue.extend(shuffled)
                self.music_cog.debug_log(guild_id, "shuffle button reshuffled queue_len=%d", len(queue))
            else:
                self.music_cog.debug_log(guild_id, "shuffle enabled but queue_len=%d; no reshuffle", len(queue))
        else:
            self.music_cog.debug_log(guild_id, "shuffle disabled")

        await self.update_player(self.music_cog.get_current_position(interaction.guild.id))

    @discord.ui.button(emoji="💡", label="Recommend", style=discord.ButtonStyle.secondary)
    async def recommend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()  # 必須在任何 async 工作前先 defer，避免 3 秒逾時
        self.music_cog.toggle_loop_mode(interaction.guild.id, LoopMode.RECOMMEND)
        await self.music_cog.ensure_recommendation_seed(interaction)
        await self.update_player(self.music_cog.get_current_position(interaction.guild.id))

    @discord.ui.button(emoji="⏹️", label="Stop", style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.music_cog.stop_and_leave(interaction)
        await interaction.response.send_message("⏹️ 播放已停止", ephemeral=True)