
import discord
from discord.ext import commands
import asyncio
import os

# --- 設定 ---
# 在此處替換成您的 Discord Bot Token
# 建議使用環境變數來管理您的 token，而不是直接寫在程式碼中
# 例如: TOKEN = os.getenv("DISCORD_TOKEN")
TOKEN = 'MTM5OTc3NzIwNDUzNTE2OTAzNA.GbxeIL.Rpog8N8Z-5ILaxhNmreGfcZN998Bzfjv37VtJU' 
INTENTS = discord.Intents.default()
INTENTS.message_content = True # 允許讀取訊息內容
INTENTS.voice_states = True    # 允許讀取語音狀態

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

