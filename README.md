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
- &button 訊息ID 按鈕編號：代替直接點擊目前有效確認卡片的按鈕；第 1 顆通常是確認，第 2 顆通常是取消或拒絕
- &snipe [數量 1-10]：查看目前頻道最近被刪除的訊息，預設列出 10 則，顯示訊息與原本傳送時間
- &react 訊息ID 表情 [表情...]：讓機器人對指定訊息加上一個或多個反應
- &delete 數量：彈出確認卡片後，刪除目前頻道最近的指定數量訊息，最多 100 則
- &give_Role 身分組ID[,身分組ID...] 人ID [備註]：一次要求給予一個或多個身分組，標記對象並彈出確認卡片，由對方接受後給予
- &give_Role force 身分組ID[,身分組ID...] 人ID [備註]：由原始管理員直接強制給予一個或多個身分組，不需要對方同意
- &give 使用者ID 貨幣種類 數量：直接增加或扣除芙帽幣、水晶或神恩；正數為增加、負數為扣除。使用 `&give all 貨幣種類 數量` 可套用到所有已建立經濟帳戶的使用者
- &create-bet [模板編號] [需要之後 start-bet 的任意文字]：在目前頻道發送建立賭盤表單按鈕；可用模板 `1`（自訂賭盤，預設 5 分鐘）、`2`（勝負預測）、`3`（二選一賭盤），按鈕後以私人表單填寫時間、標題、內容、狀況與倍率。內容可留空，時間支援 `10s`、`1m30s`、`2h`、`1d`，狀況格式為 `aaa:2,bbb:2`
- 省略第二參數代表建立後立即開放下注；第二參數只要有任何文字，就代表先建立但不開放下注，之後使用 `&start-bet 訊息ID` 才會開放
- &start-bet [訊息ID]：開放尚未開始下注的賭盤，並編輯原賭盤卡片加入下注按鈕；省略訊息 ID 時會使用目前頻道最新建立的賭盤
- 賭盤只能使用芙帽幣下注；按下狀況按鈕後以私人表單輸入下注金額，表單會顯示按下按鈕者的目前芙帽幣餘額；截止時會自動編輯賭盤並停用按鈕
- &ban-bet [賭盤訊息ID] @使用者... 選項[,選項...]：禁止指定使用者下注指定賭盤選項；省略賭盤 ID 時使用目前頻道最新賭盤，`&prohibit` 仍是相容別名
- &stop [訊息ID]：強制停止賭盤下注並停用原卡片按鈕；省略訊息 ID 時使用目前頻道最新賭盤，`&stop-bet` 也支援相同用法
- &resolve-bet 訊息ID 狀況[,狀況...]：結算賭盤；可同時結算多個結果，使用 `return` 退還所有押注
- &log 使用者ID：在目前頻道查看該使用者最近 3 天的貨幣變動紀錄
- &!say 內容：執行後刪除這則指令訊息；其他 & 指令也適用
- & 文字：等同於 &say 文字
- &! 文字：等同於 &!say 文字，執行後刪除指令訊息

`/經濟 每日簽到`、`/經濟 每小時簽到` 會依等級獲得芙帽幣；
`/經濟 餘額` 可查看芙帽幣、水晶、神恩與目前等級。簽到卡片在資源足夠時會顯示升級按鈕，
按下後還需要再次確認才會扣除費用並升級。
在伺服器 `1512762043504267284` 的頻道 `1554087496898453514` 發送任何訊息，
也會自動執行每日與每小時簽到並顯示快速簽到卡片。

`/check_master` 會以卡片顯示主奴關係，`public` 參數預設為是；關閉後只會自己看見。可使用 `/release_master` 向對方申請解除主奴契約。

`/神秘儀式 target:名字或稱號 mode:模式` 會進行一次神秘儀式，預測該對象下一場的結果；模式預設為正常，也可選公正、屠夫變強或人類變強。完成後會顯示結果卡片。

`/worship [tribute_percent]` 的獻祭比例可填 1–10，省略時為 1%。會依目前芙帽幣餘額扣除該百分比，最低扣除 100 芙帽幣；10% 獻祭有 70% 機率、1% 有 7% 機率獲得 1–5 水晶，中間比例線性計算。每日膜拜以 UTC+8 每日 00:00 重置。

PvP 指令使用 `/pvp 狀態` 開啟或關閉（Discord 的 slash command 群組不能同時擁有沒有子命令的根指令，因此狀態操作放在 `狀態` 子命令）：

- `/pvp 攻擊`：攻擊一名已開啟 PvP 的玩家；目前攻擊次數固定為 1 次，之後可再擴充至 3 次。
- `/pvp 升級`：開啟 ATK、DEF、HP、百分比、暴擊率與爆傷的直接升級介面。
- `/pvp 聖遺物`：每頁顯示 10 件聖遺物；選定單件後進入裝備／強化／分解介面，強化介面會列出完整主副詞條，升級完成後才顯示這次實際增加的副詞條。
- `/pvp 秘境`：依玩家等級選擇秘境難度並取得聖遺物。

PvP 的規則、升級數值、顏色等級與強化成本在 `commands/pvp/json/pvp_config.json`；秘境、套裝、主副詞條格式範例在 `commands/pvp/json/artifacts.json`。顏色等級為綠色 Lv.8、藍色 Lv.12、紫色 Lv.16、黃色 Lv.20，五個裝備位置為生之花、死之羽、時之沙、空之杯、理之冠。

PvP 開啟期間，簽到獎勵與賭盤中獎 payout 會依經濟等級獲得額外倍率：Lv.1 為 ×1.50，Lv.30 為 ×3.00，中間等級線性增加；PvP 關閉、被強制關閉或賭盤退款時不套用。

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
commands/pvp/            PvP 指令、傷害計算、聖遺物與秘境
commands/pvp/json/       PvP 規則、套裝、詞條與秘境的 JSON 設定
```
