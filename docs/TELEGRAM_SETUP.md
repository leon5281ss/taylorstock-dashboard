# Telegram 主動提醒（預設關閉）/ Telegram notifications (opt-in)

本功能只有在使用者完成憑證和收件者設定、明確開啟變數後才會發送。未設定時 notify job 跳過；PR／push 事件不傳送。不公開成本、持股數、私人帳本、Bot Token、Chat ID、私人通知狀態。

## GitHub 中英文對照設定

1. 由 Telegram 的官方 @BotFather 建立機器人，自己先對 Bot 傳送 /start，取得正確 Chat ID。**不要貼到聊天、PR 或公開檔案。**
2. 另外在 GitHub 建立**私人儲存庫 / Private repository**，初始化 README，預設分支 main，用於 telegram-ledger.json；請勿與公開的 taylorstock-dashboard 共用儲存庫。建立只允許這個私人 repo「內容／Contents: Read and write」的細粒度 PAT。
3. 主專案「設定／Settings → 秘密與變數／Secrets and variables → 行動／Actions → 秘密／Secrets」，設定四個 Repository secrets：
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID
   - TELEGRAM_LEDGER_TOKEN（僅限私有庫的 GitHub PAT）
   - TELEGRAM_LEDGER_REPO（owner/private-repository）
4. 在「變數／Variables」設定 TELEGRAM_NOTIFICATIONS_ENABLED。**沒有確認手機送達之前保持未設定或 false。** 明確改成 true 後，main 的排程或手動日報才會送出；程式 push 或 PR 不會推送。
5. 先下載 Daily Stock Report 的 public-daily-report artifact，使用 python scripts/send_telegram.py --report report/stocks.json --dry-run。dry-run 不呼叫 Telegram、不寫私有庫。部署後啟用時，以「行動／Actions → Daily Stock Report → notify」檢查第一次真實手機送達。
6. 要立即停止推送，將變數改為 false，無需更換 FinMind Token。

## 安全與資料邊界

每日交易日摘要發一次；後續 21:20／21:40 只發新增或中升高的警報，使用與 PR #2 相同的 eventKey。為防重複，先寫私人 ledger 的 pending 再發 Telegram；確認 API ok=true 才寫 sent。網路結果不確定寫 unknown，**不自動重試 pending/unknown**，以避免盲目重送，但可能漏發，須人工核對。Telegram 不提供此流程可依賴的 exactly-once 保證。

訊息長度限制為約3300字；僅公開市場代號、日期、規則、風險與摘要。沒有足夠完整行情（少於15／22）或使用過期資料時停止通知。政策公告是候選線索，不能當作官股實際買賣、國安基金實際進場證據。

參考 https://core.telegram.org/bots/api#sendmessage
