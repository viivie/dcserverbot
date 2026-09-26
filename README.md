# Python Discord bot

這是原 TypeScript Discord 機器人的 Python Gateway 版。它保留 `/worship`、台北時間每日一次、連續天數、總次數、目標成員頭像快取與 Embed 回覆。

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

資料會寫入 `data/worship.sqlite3`，使用 Python 內建的 SQLite，不需要另外安裝資料庫服務。ACLClouds 免費方案請定期備份整個 `data/` 資料夾；也可以用 `DATA_FILE` 指定其他 SQLite 檔案路徑。若舊版本仍有 `worship.json`，第一次啟動會自動匯入資料。

ACLClouds 可直接使用預設的 `main.py` 啟動入口。這是 Discord Gateway Bot，不需要公開 HTTP 網址；程式啟動後會自動同步 `/worship`，並清除舊的全域 `/worship`，避免 Discord 顯示兩個。

## 模組結構

```text
main.py                 ACLClouds 預設入口
bot.py                  Gateway 啟動入口
config.py               環境變數與共用設定
storage.py              SQLite 儲存
worship.py              膜拜專用規則、文字與 Embed 設定
discord_api.py          Discord REST 與頭像查詢
gateway.py              Gateway 啟動與指令同步
commands/__init__.py    指令註冊表
commands/context.py     指令共用依賴
commands/worship.py     /worship 指令
```

新增指令時，在 `commands/` 新增模組，例如 `commands/ping.py`，再在 `commands/__init__.py` 的 `register_all()` 加上 `register_ping(...)`。ACLClouds 部署時必須連同整個 `commands/` 資料夾一起上傳。
