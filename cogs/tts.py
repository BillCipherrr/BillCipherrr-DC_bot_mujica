import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os
import io
import json
import tempfile
import asyncio

class TTSCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.minimax_api_key = os.getenv("MINIMAX_API_KEY")
        if not self.minimax_api_key:
            print("警告：未找到 MINIMAX_API_KEY 環境變數，TTS 功能將無法使用。")

    @app_commands.command(name="tts", description="使用 MiniMax 將文字轉為語音並播放")
    @app_commands.describe(
        text="要轉換為語音的文字",
        voice="moss_audio_98193709-7850-11f0-bb73-1e2a4cfcd245", ##AI王瑞賢
        speed="語速 (預設: 1.0)",
        volume="音量 (預設: 1.0)"
    )
    async def tts(self, interaction: discord.Interaction, text: str, voice: str = "female-shaonv", speed: float = 1.0, volume: float = 1.0):
        if not self.minimax_api_key:
            await interaction.response.send_message("❌ TTS 功能未正確設定，請聯絡管理員設定 `MINIMAX_API_KEY`。", ephemeral=True)
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ 您需要先加入一個語音頻道！", ephemeral=True)
            return

        if len(text) > 300:
            await interaction.response.send_message("❌ 文字長度不得超過 300 字，請縮短後重試。", ephemeral=True)
            return

        await interaction.response.defer()

        # Connect to voice channel
        voice_channel = interaction.user.voice.channel
        guild = interaction.guild
        voice_client = guild.voice_client

        if voice_client:
            if voice_client.channel.id != voice_channel.id:
                await voice_client.move_to(voice_channel)
        else:
            voice_client = await voice_channel.connect()

        if voice_client.is_playing():
             await interaction.followup.send("❌ 機器人目前正在播放其他內容，請稍後再試。", ephemeral=True)
             return

        # Prepare HTTP request to MiniMax
        url = "https://api.minimax.io/v1/t2a_v2"
        headers = {
            'Authorization': f'Bearer {self.minimax_api_key}',
            'Content-Type': 'application/json'
        }

        # We will use speech-2.8-turbo or speech-2.6-turbo
        payload = {
            "model": "speech-2.-turbo",
            "text": text,
            "stream": False,
            "output_format": "hex",
            "voice_setting": {
                "voice_id": voice,
                "speed": speed,
                "vol": volume,
                "pitch": 0
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status != 200:
                        err_text = await response.text()
                        await interaction.followup.send(f"❌ MiniMax API 錯誤: HTTP {response.status} - {err_text}")
                        return

                    data = await response.json()

                    if "base_resp" in data and data["base_resp"]["status_code"] != 0:
                        await interaction.followup.send(f"❌ API 回傳錯誤: {data['base_resp']['status_msg']}")
                        return

                    if "data" not in data or "audio" not in data["data"]:
                        await interaction.followup.send("❌ API 回傳資料格式不符。")
                        return

                    hex_audio = data["data"]["audio"]
                    if not hex_audio:
                        await interaction.followup.send("❌ API 回傳音檔為空。")
                        return

                    audio_bytes = bytes.fromhex(hex_audio)

            # Write audio to a temporary file
            fd, temp_path = tempfile.mkstemp(suffix=".mp3")
            with os.fdopen(fd, 'wb') as f:
                f.write(audio_bytes)

            audio_source = discord.FFmpegPCMAudio(temp_path)

            def after_playing(error):
                try:
                    os.remove(temp_path)
                except Exception as e:
                    print(f"刪除暫存檔 {temp_path} 時發生錯誤: {e}")

            voice_client.play(audio_source, after=after_playing)
            await interaction.followup.send(f"🗣️ **播放語音:** {text[:50]}{'...' if len(text) > 50 else ''}")

        except Exception as e:
            await interaction.followup.send(f"❌ 發生未預期錯誤: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(TTSCog(bot))
