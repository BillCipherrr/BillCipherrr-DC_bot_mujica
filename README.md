# Discord Music Bot - Mujica

[中文版](./README_zh-TW.md) | English

A feature-rich Discord music bot built with discord.py, supporting playback from various audio/video platforms via yt-dlp, intelligent recommendations, and comprehensive playlist management.

## ✨ Features

### 🎵 Core Music Features
- **Multi-Platform Support**: Play individual songs or entire playlists from various audio/video platforms via yt-dlp
- **Queue Management**: Intelligent queue system with visual display in player
- **Multiple Loop Modes**:
  - None: Play songs in order
  - Single Song: Repeat current song
  - Queue: Repeat entire queue
  - Shuffle: Random playback
  - Recommend: Auto-play recommended songs based on current track
- **Volume Control**: Adjustable volume with persistent settings per server
- **Real-time Progress**: Live progress bar with 10-second auto-update

### 🤖 Smart Features
- **Intelligent Recommendations**: YouTube API-powered song recommendations with duplicate detection
- **Auto-disconnect**: Automatically leaves channel after 5 minutes of inactivity
- **Playlist Support**: Server administrators can enable/disable playlist support
- **Play History**: Track and display user and server listening history

### 🎮 Interactive Controls
- **Button-based Player**: Intuitive control interface with:
  - Play/Pause toggle
  - Skip to next song
  - Volume adjustment
  - Loop mode toggles
- **Progress Display**: Shows current position, duration, and visual progress bar
- **Queue Preview**: Display upcoming songs directly in player embed

### 📊 History & Statistics
- **User History**: View personal listening history with play counts
- **Server History**: Server-wide playback statistics
- **SQLite Database**: Persistent storage for songs and play history

## 📋 Prerequisites

- Python 3.8 or higher
- FFmpeg installed on your system
- Node.js 20+ installed and on PATH (optional, but recommended — see note below)
- Discord Bot Token
- YouTube Data API v3 Key (optional, for recommendation features)

## 🚀 Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/BillCipherrr-DC_bot_mujica.git
cd BillCipherrr-DC_bot_mujica
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Install FFmpeg**
   - **Ubuntu/Debian**: `sudo apt-get install ffmpeg`
   - **macOS**: `brew install ffmpeg`
   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

4. **Install Node.js (recommended)**

   yt-dlp uses Node.js as a JavaScript runtime to decrypt YouTube's signature and unlock the stronger `web`/`web safari` clients. Without it, yt-dlp silently falls back to the JS-less `android_vr` client, which is much more prone to 403 errors on stream URLs.
   - **Windows**: `winget install --id OpenJS.NodeJS.LTS -e` (open a **new** terminal afterward so the updated PATH takes effect)
   - **Ubuntu/Debian**: `sudo apt-get install nodejs` or install via [nvm](https://github.com/nvm-sh/nvm)
   - **macOS**: `brew install node`

   Verify with `node --version` (needs to be v20+). If the bot prints `警告：找不到 node 執行檔` (or the English equivalent) on startup, Node isn't on the PATH of the process running the bot.

5. **Set up environment variables**

Create a `.env` file in the project root:
```env
DISCORD_TOKEN=your_discord_bot_token_here
YOUTUBE_API_KEY=your_youtube_api_key_here
```

6. **Run the bot**
```bash
python bot.py
```

## 🎯 Commands

### Music Commands
- `/play <url>` - Play a song or playlist from supported platforms
- `/leave` - Disconnect bot and clear queue
- `/sites` - View supported audio/video platforms

### Player Controls (Button Interface)
- **⏸️ Pause** - Pause/Resume playback
- **⏭️ Skip** - Skip to next song
- **🔁 Loop One** - Toggle single song repeat
- **🔁 Loop Queue** - Toggle queue repeat
- **🔀 Shuffle** - Toggle shuffle mode
- **🎲 Recommend** - Toggle auto-recommendation mode
- **🔊 Volume** - Adjust playback volume

### History Commands
- `/history user [user]` - View listening history for a user
- `/history server` - View server-wide listening history

### Admin Commands
- `/settings` - Open bot settings panel (requires Manage Server permission)
  - Toggle playlist support on/off
- `/music_debug` - Toggle music system debug logging (requires Manage Server permission)

## 🏗️ Project Structure

```
BillCipherrr-DC_bot_mujica/
├── bot.py                 # Main bot entry point
├── database.py            # SQLite database functions
├── requirements.txt       # Python dependencies
├── cogs/
│   ├── music.py          # Music playback logic
│   └── history.py        # History tracking commands
└── views/
    ├── player_view.py    # Interactive player UI
    └── settings_view.py  # Admin settings panel
```

## 🔧 Configuration

### YouTube API Setup
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable YouTube Data API v3
4. Create credentials (API Key)
5. Add the API key to your `.env` file

### Discord Bot Setup
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to "Bot" section and create a bot
4. Enable the following Privileged Gateway Intents:
   - Message Content Intent
   - Server Members Intent
5. Copy the bot token to your `.env` file
6. Invite the bot with these permissions:
   - Send Messages
   - Embed Links
   - Connect
   - Speak
   - Use Voice Activity

## 🎨 Features in Detail

### Recommendation System
The bot uses YouTube API to find related videos based on:
- Current playing song
- Prevents duplicate recommendations
- Filters out recently played songs (last 20 tracks)
- Normalizes titles to avoid re-uploads

### Database Schema
- **songs**: Stores unique songs with URL, title, and duration
- **play_history**: Records every play with guild, user, timestamp

## 🛠️ Dependencies

- `discord.py[voice]` - Discord API wrapper with voice support
- `yt-dlp` - YouTube video/audio downloader
- `python-dotenv` - Environment variable management
- `google-api-python-client` - YouTube API client

## 📝 Notes

- The bot automatically syncs slash commands on startup
- Opus library is required for voice support (auto-loaded)
- SQLite database is created automatically on first run
- Playlist support can be disabled per server for performance

## 🐛 Troubleshooting

**Bot doesn't join voice channel:**
- Ensure FFmpeg is properly installed
- Check that Opus library is loaded (console output)

**Streams frequently fail with 403 errors / console shows "找不到 node 執行檔":**
- Install Node.js 20+ (see Installation step 4) and make sure `node --version` works in the same terminal/session that runs `python bot.py`
- On Windows, PATH changes from a fresh install only apply to newly opened terminals — restart your terminal and reactivate your virtualenv/conda env after installing Node

**Recommendations not working:**
- Verify YouTube API key is set in `.env`
- Check API quota limits

**Commands not appearing:**
- Wait a few minutes for Discord to sync commands
- Try removing and re-inviting the bot

## 📄 License

This project is open source and available under the MIT License.

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!

## 👤 Author

BillCipherrr

---

Made with ❤️ using discord.py
