
import discord
from discord.ext import commands
import asyncio
import os
import socket
import database
from dotenv import load_dotenv
import logging
import aiohttp
from aiohttp import client_exceptions

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
    _opus_candidates = [
        'libopus.so.0',          # Ubuntu/Debian
        'libopus.so.1',          # 部分 Linux 發行版
        '/opt/homebrew/lib/libopus.dylib',   # macOS Apple Silicon (Homebrew)
        '/usr/local/lib/libopus.dylib',      # macOS Intel (Homebrew)
        'opus',
    ]
    for _lib in _opus_candidates:
        try:
            discord.opus.load_opus(_lib)
            print(f"Opus loaded with {_lib}")
            break
        except OSError:
            continue
    else:
        print("警告：無法載入 Opus，語音功能將失敗")
else:
    print("Opus already loaded")

# --- Bot 初始化 ---
def create_bot() -> commands.Bot:
    """建立並回傳新的 Bot 實例。"""
    connector = aiohttp.TCPConnector(family=socket.AF_INET, ttl_dns_cache=300)
    bot = commands.Bot(command_prefix='/', intents=INTENTS, connector=connector)

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

    return bot


async def load_cogs(bot: commands.Bot):
    """載入所有在 cogs 資料夾中的模組"""
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f'Loaded cog: {filename}')
            except Exception as e:
                print(f'Failed to load cog {filename}: {e}')


def _retry_delay(attempt: int) -> int:
    """根據重試次數計算延遲秒數（上限 60 秒）。"""
    return min(60, 2 ** min(attempt, 6))


async def start_bot_with_retry():
    """以手動重試方式啟動 Bot，避免網路逾時時直接崩潰。"""
    attempt = 0
    while True:
        bot = create_bot()
        try:
            async with bot:
                await load_cogs(bot)
                # 關閉 discord.py 內建重連流程，避免極端網路狀況下觸發 ws 為 None 的已知崩潰路徑
                await bot.start(TOKEN, reconnect=False)
                return
        except (client_exceptions.ClientError, asyncio.TimeoutError, discord.GatewayNotFound) as e:
            attempt += 1
            delay = _retry_delay(attempt)
            logging.warning("Discord Gateway 連線失敗（第 %s 次）：%s", attempt, e)
            logging.info("%s 秒後重試連線...", delay)
            await asyncio.sleep(delay)
        except RuntimeError as e:
            if "Session is closed" not in str(e):
                raise
            attempt += 1
            delay = _retry_delay(attempt)
            logging.warning("Discord HTTP Session 已關閉（第 %s 次）：%s", attempt, e)
            logging.info("%s 秒後重建連線...", delay)
            await asyncio.sleep(delay)
        except Exception:
            raise

async def main():
    """主函式，用來啟動機器人"""
    # 初始化資料庫
    database.setup_database()
    await start_bot_with_retry()

if __name__ == "__main__":
    # 為了在 Windows 和 Linux 上都能正常運作
    # 我們使用 asyncio.run() 來啟動非同步主函式
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot is shutting down...")

