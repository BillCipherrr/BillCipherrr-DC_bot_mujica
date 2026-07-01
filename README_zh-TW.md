# Discord 音樂機器人 - Mujica

[English](./README.md) | 中文版

一個功能豐富的 Discord 音樂機器人，使用 discord.py 構建，透過 yt-dlp 支援多種影音平台播放、智能推薦和完整的播放列表管理。

## ✨ 功能特色

### 🎵 核心音樂功能
- **多平台支援**：透過 yt-dlp 支援播放多種影音平台上的單曲或完整播放列表
- **佇列管理**：智慧型佇列系統，在播放器中視覺化顯示
- **多種循環模式**：
  - 無循環：依序播放歌曲
  - 單曲循環：重複播放當前歌曲
  - 佇列循環：重複播放整個佇列
  - 隨機播放：隨機選擇歌曲
  - 推薦模式：根據當前歌曲自動播放推薦歌曲
- **音量控制**：可調整音量，每個伺服器獨立設定
- **即時進度**：即時進度條，每 10 秒自動更新

### 🤖 智能功能
- **智能推薦**：基於 YouTube API 的歌曲推薦，具備重複檢測功能
- **自動斷線**：閒置 5 分鐘後自動離開頻道
- **播放列表支援**：伺服器管理員可啟用/停用播放列表功能
- **播放歷史**：追蹤並顯示使用者和伺服器的聆聽記錄

### 🎮 互動式控制
- **按鈕式播放器**：直覺的控制介面，包含：
  - 播放/暫停切換
  - 跳過至下一首
  - 音量調整
  - 循環模式切換
- **進度顯示**：顯示當前位置、總時長和視覺化進度條
- **佇列預覽**：直接在播放器嵌入中顯示待播歌曲

### 📊 歷史記錄與統計
- **使用者歷史**：查看個人聆聽記錄和播放次數
- **伺服器歷史**：全伺服器的播放統計
- **SQLite 資料庫**：歌曲和播放記錄的持久化儲存

## 📋 系統需求

- Python 3.8 或更高版本
- 系統需安裝 FFmpeg
- Discord Bot Token
- YouTube Data API v3 金鑰（選用，用於推薦功能）

## 🚀 安裝步驟

1. **克隆專案**
```bash
git clone https://github.com/yourusername/BillCipherrr-DC_bot_mujica.git
cd BillCipherrr-DC_bot_mujica
```

2. **安裝依賴套件**
```bash
pip install -r requirements.txt
```

3. **安裝 FFmpeg**
   - **Ubuntu/Debian**：`sudo apt-get install ffmpeg`
   - **macOS**：`brew install ffmpeg`
   - **Windows**：從 [ffmpeg.org](https://ffmpeg.org/download.html) 下載

4. **設定環境變數**

在專案根目錄建立 `.env` 檔案：
```env
DISCORD_TOKEN=你的Discord機器人Token
YOUTUBE_API_KEY=你的YouTube_API金鑰
```

5. **啟動機器人**
```bash
python bot.py
```

## 🎯 指令說明

### 音樂指令
- `/play <url>` - 播放支援平台上的歌曲或播放列表
- `/leave` - 讓機器人離開頻道並清空佇列
- `/sites` - 查看本機器人支援的影音平台

### 播放器控制（按鈕介面）
- **⏸️ 暫停** - 暫停/繼續播放
- **⏭️ 跳過** - 跳到下一首歌
- **🔁 單曲循環** - 切換單曲重複播放
- **🔁 佇列循環** - 切換佇列重複播放
- **🔀 隨機播放** - 切換隨機播放模式
- **🎲 推薦模式** - 切換自動推薦模式
- **🔊 音量** - 調整播放音量

### 歷史記錄指令
- `/history user [使用者]` - 查看使用者的聆聽記錄
- `/history server` - 查看伺服器的聆聽記錄

### 管理員指令
- `/settings` - 開啟機器人設定面板（需要管理伺服器權限）
  - 切換播放列表支援開關
- `/music_debug` - 切換音樂系統除錯日誌模式（需要管理伺服器權限）

## 🏗️ 專案結構

```
BillCipherrr-DC_bot_mujica/
├── bot.py                 # 機器人主程式入口
├── database.py            # SQLite 資料庫功能
├── requirements.txt       # Python 依賴套件
├── cogs/
│   ├── music.py          # 音樂播放邏輯
│   └── history.py        # 歷史記錄指令
└── views/
    ├── player_view.py    # 互動式播放器介面
    └── settings_view.py  # 管理員設定面板
```

## 🔧 配置說明

### YouTube API 設定
1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 建立新專案
3. 啟用 YouTube Data API v3
4. 建立憑證（API 金鑰）
5. 將 API 金鑰加入 `.env` 檔案

### Discord 機器人設定
1. 前往 [Discord 開發者入口](https://discord.com/developers/applications)
2. 建立新應用程式
3. 進入「Bot」區塊並建立機器人
4. 啟用以下特權閘道意圖（Privileged Gateway Intents）：
   - Message Content Intent（訊息內容意圖）
   - Server Members Intent（伺服器成員意圖）
5. 複製機器人 Token 到 `.env` 檔案
6. 邀請機器人時需要以下權限：
   - 發送訊息
   - 嵌入連結
   - 連接語音
   - 說話
   - 使用語音活動

## 🎨 功能詳解

### 推薦系統
機器人使用 YouTube API 根據以下條件尋找相關影片：
- 當前播放的歌曲
- 防止重複推薦
- 過濾最近播放的歌曲（最近 20 首）
- 標題正規化以避免重新上傳的版本

### 資料庫架構
- **songs**：儲存歌曲的唯一 URL、標題和時長
- **play_history**：記錄每次播放，包含伺服器、使用者和時間戳記

## 🛠️ 依賴套件

- `discord.py[voice]` - Discord API 封裝，包含語音支援
- `yt-dlp` - YouTube 影片/音訊下載器
- `python-dotenv` - 環境變數管理
- `google-api-python-client` - YouTube API 客戶端

## 📝 注意事項

- 機器人啟動時會自動同步斜線指令
- 語音支援需要 Opus 函式庫（自動載入）
- SQLite 資料庫在首次執行時自動建立
- 播放列表支援可依伺服器停用以提升效能

## 🐛 疑難排解

**機器人無法加入語音頻道：**
- 確認 FFmpeg 已正確安裝
- 檢查 Opus 函式庫是否已載入（查看控制台輸出）

**推薦功能無法使用：**
- 驗證 YouTube API 金鑰是否已設定在 `.env`
- 檢查 API 配額限制

**指令沒有顯示：**
- 等待幾分鐘讓 Discord 同步指令
- 嘗試移除並重新邀請機器人

## 📄 授權

本專案為開源專案，採用 MIT 授權條款。

## 🤝 貢獻

歡迎貢獻、回報問題和功能請求！

## 👤 作者

BillCipherrr

---

使用 discord.py 用 ❤️ 製作
