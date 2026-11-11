# Telegram 推播設計（未啟用）

本 PR 只實作純函式 notification_plan(payload, delivered) 與去重測試。不建立 Bot、不發手機訊息、不新增外部帳戶或排程，不在前端呼叫 Telegram；啟用須另經使用者確認。

## 21:00、21:20、21:40

- 保留既有臺灣時間三次收集。21:00 首次摘要；後兩次只處理新事件或同事件升級，報告本身仍可更新。
- 個股只選中／高級別警報；一般買超觀察不推送。市場公告單獨一則，不複製成 22 則。資料品質故障另為系統通知，不冒充個股高風險。
- eventKey = SHA256(scope + 股票代號 + 規則 + 實際資料交易日期 + 文章識別)，不含 generatedAt、執行批次或易變標題。市場新聞用發布日期與正規化 URL 雜湊，跨來源去重。
- 同 key、同級別不重發；中升高可發升級；次日真正新增的技術／籌碼事件用新交易日。延遲資料仍用舊資料日期，不能因 21:20 重跑就改成新事件。未知發布日期或非近期公告不推送。
- planned 不是 delivered。送出成功才記錄已送級別；本 PR 函式不會把計畫誤標已送達，失敗可重試。

## 後續啟用要求

1. 僅把 TELEGRAM_BOT_TOKEN、TELEGRAM_CHAT_ID 放 Actions Secrets，與 FINMIND_TOKEN 分開。聊天室 ID、收件者及 Token 不進公開 JSON、Pages、artifact 或日誌。
2. 另建 main-only notification job、全域單一 concurrency 群組，不能讓 PR 或開發分支傳送；先跑 dry-run 並人工確認收件者。
3. 使用私有持久化狀態庫（例如有唯一 eventKey 的資料表）保存已送級別、message_id、時間與 pending/sent/unknown 狀態，以原子鎖避免重跑競態。不能依賴 runner 本機或可被淘汰的 Actions cache 當唯一帳本；本 PR 尚未建置此服務。
4. HTTP 成功且 Telegram ok=true 後才提交 sent；網路逾時而送達不明記 unknown，避免立即盲目重送。Telegram sendMessage 沒有本設計可依賴的 exactly-once 保證，需人工處理不確定結果。
5. 依 retry_after 處理限流；拒絕認證／封鎖停止。API URL 含 Bot Token，因此所有例外、request URL、回應原文皆不得寫日誌。
6. 訊息只允許公開代號、日期、規則、風險與官方連結；不傳持股、成本、損益、原始報告 JSON。純文字分段，每段保守限制 3500 字元。

參考：[Telegram 官方 Bot API](https://core.telegram.org/bots/api#sendmessage)。啟用前須再驗證官方規格與實際手機送達，不以離線去重測試冒充推播成功。
