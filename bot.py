
import discord
from discord.ext import commands
import asyncio
import os
import database
from dotenv import load_dotenv
import logging

# 載入 .env 檔案中的環境變數
load_dotenv()

# --- 設定 ---
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("錯誤：請在 .env 檔案中設定 DISCORD_TOKEN") 
INTENTS = discord.Intents.default()
INTENTS.message_content = True # 允許讀取訊息內容
INTENTS.voice_states = True    # 允許讀取語音狀態

# --- 日誌設定 ---
logging.basicConfig(level=logging.INFO)

# --- 確保 Opus 已載入 ---
# 某些系統不會自動找到 libopus，手動指定共享庫名稱避免語音連線立即斷線
if not discord.opus.is_loaded():
    try:
        discord.opus.load_opus('libopus.so.0')
        print("Opus loaded with libopus.so.0")
    except OSError:
        # 後備名稱，有些發行版可能不同
        try:
            discord.opus.load_opus('opus')
            print("Opus loaded with opus")
        except Exception as e:
            print(f"警告：無法載入 Opus，語音功能將失敗：{e}")
else:
    print("Opus already loaded")

# --- Bot 初始化 ---
bot = commands.Bot(command_prefix='/', intents=INTENTS)

@bot.event
async def on_ready():
    """當機器人準備好時執行的事件"""
    print(f'Logged in as {bot.user.name}')
    print(f'Bot ID: {bot.user.id}')
    print('------')
    # 同步斜線指令
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

async def load_cogs():
    """載入所有在 cogs 資料夾中的模組"""
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f'Loaded cog: {filename}')
            except Exception as e:
                print(f'Failed to load cog {filename}: {e}')

async def main():
    """主函式，用來啟動機器人"""
    # 初始化資料庫
    database.setup_database()
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)

if __name__ == "__main__":
    # 為了在 Windows 和 Linux 上都能正常運作
    # 我們使用 asyncio.run() 來啟動非同步主函式
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot is shutting down...")

