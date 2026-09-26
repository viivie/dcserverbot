# Python Discord bot

## 啟動

```bash
cd /home/container
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 編輯 .env 填入 Discord Bot Token
python bot.py gateway
```

資料會存在 `data/worship.sqlite3`

## 結構

```text
main.py                 ACLClouds 預設入口
bot.py                  Gateway 啟動入口
config.py               環境變數與共用設定
storage.py              SQLite 儲存
discord_api.py          Discord REST 與頭像查詢
gateway.py              Gateway 啟動與指令同步
commands/__init__.py    指令註冊表
commands/XXXXXXXXXXX.py 各種指令的文件，可能有複數指令會在同個文件
```


