import discord

class SettingsView(discord.ui.View):
    def __init__(self, music_cog, guild_id):
        super().__init__(timeout=None)
        self.music_cog = music_cog
        self.guild_id = guild_id
        self.update_buttons()

    def update_buttons(self):
        """根據目前的設定更新按鈕的狀態。"""
        is_enabled = self.music_cog.is_playlist_enabled(self.guild_id)
        if is_enabled:
            self.toggle_playlist_button.label = "播放列表 (已啟用)"
            self.toggle_playlist_button.style = discord.ButtonStyle.success
        else:
            self.toggle_playlist_button.label = "播放列表 (已停用)"
            self.toggle_playlist_button.style = discord.ButtonStyle.danger

    @discord.ui.button(label="", style=discord.ButtonStyle.secondary, custom_id="toggle_playlist_button")
    async def toggle_playlist_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """切換播放列表功能的按鈕回呼。"""
        # 再次檢查權限，確保安全
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ 您需要擁有「管理伺服器」的權限才能進行此操作。", ephemeral=True)
            return

        # 切換設定
        current_status = self.music_cog.is_playlist_enabled(self.guild_id)
        self.music_cog.playlist_enabled[self.guild_id] = not current_status

        # 更新按鈕外觀並重新整理 View
        self.update_buttons()
        await interaction.response.edit_message(view=self)
