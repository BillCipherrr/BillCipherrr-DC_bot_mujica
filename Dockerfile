# 1. 使用 Python 3.12-slim 作為基礎映像
FROM python:3.12-slim

# 2. 安裝 FFmpeg
#    - apt-get update 更新套件列表
#    - apt-get install -y ffmpeg 安裝 FFmpeg，-y 會自動確認安裝
#    - 建議將兩者用 && 連接，確保使用最新的列表並只建立一個映像層
RUN apt-get update && apt-get install -y ffmpeg

# 3. 設定容器內的工作目錄
WORKDIR /app

# 4. 複製 requirements.txt 並安裝 Python 依賴
#    這一步驟被刻意放在複製完整程式碼之前，以利用 Docker 的快取機制
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 複製整個專案的程式碼到工作目錄
COPY . .

# 6. 設定啟動容器時要執行的預設指令
CMD ["python", "bot.py"]