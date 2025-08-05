import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import database
import datetime

class HistoryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    history_group = app_commands.Group(name="history", description="查詢播放歷史紀錄")

    @history_group.command(name="user", description="查詢您或某位使用者的播放歷史")
    async def user_history(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        target_user = user or interaction.user
        history = database.get_user_history(target_user.id)

        if not history:
            await interaction.response.send_message(f"{target_user.mention} 沒有任何播放紀錄。", ephemeral=True)
            return

        embed = discord.Embed(title=f"{target_user.display_name} 的播放歷史", color=discord.Color.blue())
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        description = ""
        for record in history:
            # 將 timestamp 轉換為 Discord 的相對時間格式
            timestamp = f"<t:{int(record['last_played'])}:R>"
            play_count = f" `(x{record['play_count']})`" if record['play_count'] > 1 else ""
            description += f"- [{record['title']}]({record['youtube_url']}){play_count} {timestamp}\n"
        
        embed.description = description
        await interaction.response.send_message(embed=embed)

    @history_group.command(name="server", description="查詢這個伺服器的播放歷史")
    async def server_history(self, interaction: discord.Interaction):
        history = database.get_server_history(interaction.guild.id)

        if not history:
            await interaction.response.send_message("這個伺服器沒有任何播放紀錄。", ephemeral=True)
            return

        embed = discord.Embed(title=f"{interaction.guild.name} 的播放歷史", color=discord.Color.gold())
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        description = ""
        for record in history:
            user = self.bot.get_user(record['user_id']) or f"<@{record['user_id']}>"
            timestamp = f"<t:{int(record['last_played'])}:R>"
            play_count = f" `(x{record['play_count']})`" if record['play_count'] > 1 else ""
            description += f"- **{record['title']}**{play_count} - 由 {user.mention if isinstance(user, discord.User) else user} 點播 {timestamp}\n"

        embed.description = description
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(HistoryCog(bot))