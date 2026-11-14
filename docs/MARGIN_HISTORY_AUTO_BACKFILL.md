# 官方融資融券歷史自動回補（獨立研究資料）

## 目的與資料邊界
官方上市 MI_MARGN 與上櫃 margin/balance 已經通過單日歷史資料驗證，首日檔案 data/margin_research/2026-11-13.json.gz 已成功保存。本流程讓多日融資融券研究資料持續累積。

- **僅使用 data/market_daily 與 data/market_backfill_pilot 已保存的日期作為請求名單**，不自行猜測交易日，也不虛構歷史來源。
- 每次最多新增12個經核驗日期，最多20次嘗試；依日期由近到遠回補，成功的檔案不重複覆寫，無法取得來源會記錄在工作日誌及診斷檔。
- 每個官方來源查詢都應有明確的請求日期與回傳日期相符；每日資料中，上市至少650檔，上櫃至少450檔，來源 schema 與交易單位標記須通過品質檢查。
- 上市餘額單位尚不能證實是「股」，上櫃明確是「張」；兩者**不可直接換算成同一份風險分數**，不可把當日盤後數字視為當日盤中已公開。
- 公司母體是目前官方上市／上櫃名單，尚不包含當時已下市股票；資料是研究用未來因子候選，非歷史可交易訊號。
- 首次合併主分支自動執行一批，之後以台灣時間02:10、10:10、18:10三次排程追加（GitHub Actions 執行時間可能延遲）。
- 使用既有安全推送 scripts/safe_commit_public_data.sh，以失敗即停、不強制覆寫的方式應對其他資料工作流程同時更新主分支。
- Actions → Automatic Official Margin Balance Research Backfill → Run workflow 可手動觸發；執行結果另存30天診斷 Artifact automatic-margin-research-batch-status。

## 注意
研究資料存放於 data/margin_research，不會修改正式價格、22檔追蹤、Telegram 設定或私人持股；top10 永遠為 null、publishable=false、marginFactorReady=false。

若將來進入策略回測，還需先核實盤後發布時間、交易單位、減資股本異動、當時公司母體、除權息調整，以及台灣上市櫃實際手續費、證交稅與滑價。
