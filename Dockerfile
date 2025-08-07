# 使用官方 Python 映像作為基礎
FROM python:3.10-slim

# 設定工作目錄
WORKDIR /app

# 複製 requirements.txt 並安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製所有專案檔案到容器中
COPY . .

# 定義容器啟動時執行的命令
CMD ["python", "bot.py"]
