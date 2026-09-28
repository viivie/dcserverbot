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

資料會存在 `data/database.db`。程式不再讀取舊的 JSON 資料檔。

若要備份到 Google Drive，請把 OAuth Client JSON 放到
`credentials/google_drives.json`（或用 `GOOGLE_DRIVE_OAUTH_CLIENT_FILE` 指定其他路徑），
再執行一次 `python google_drive_auth.py` 完成瀏覽器授權。授權產生的
`credentials/google_drive_token.json` 也要一起放到部署環境。
接著在 `.env` 填入目標資料夾 ID `GOOGLE_DRIVE_FOLDER_ID`，以及可選的備份間隔
`GOOGLE_DRIVE_BACKUP_INTERVAL`（秒）。OAuth 可以使用一般「我的雲端硬碟」資料夾，
也可以使用 Shared Drive。
機器人會定期以 SQLite snapshot 覆蓋 Drive 裡的 `database.db`。

## 管理員 & 指令

原管理員 ID 1246096914634510417 預設可以使用全部管理員指令。其他使用者必須先由原管理員授權：

- &grant 使用者ID say button snipe：授權一個或多個指令
- &revoke 使用者ID say：撤銷指定權限
- &revoke 使用者ID all：撤銷該使用者全部權限
- &perms 使用者ID：查看權限
- &help：以私人訊息顯示自己可用的指令
- &snipe [數量 1-10]：查看目前頻道最近被刪除的訊息，預設列出 10 則，顯示訊息與原本傳送時間
- &react 訊息ID 表情 [表情...]：讓機器人對指定訊息加上一個或多個反應
- &delete 數量：彈出確認卡片後，刪除目前頻道最近的指定數量訊息，最多 100 則
- &give 身分組ID 人ID [備註]：標記對象並彈出確認卡片，由對方接受後給予身分組
- &!say 內容：執行後刪除這則指令訊息；其他 & 指令也適用
- & 文字：等同於 &say 文字
- &! 文字：等同於 &!say 文字，執行後刪除指令訊息

`/check_master` 會以卡片顯示主奴關係，`public` 參數預設為是；關閉後只會自己看見。可使用 `/release_master` 向對方申請解除主奴契約。

`/神秘儀式 target:名字或稱號 mode:模式` 會進行一次神秘儀式，預測該對象下一場的結果；模式預設為正常，也可選公正、屠夫變強或人類變強。完成後會顯示結果卡片。

刪除訊息紀錄會保存最近 500 則，並依頻道查詢。Discord 只有在刪除事件發生時仍快取該訊息時，才能提供完整原文；超出訊息快取範圍的舊訊息可能無法被 &snipe 還原。

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
