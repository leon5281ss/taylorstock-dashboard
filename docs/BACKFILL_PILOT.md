# 官方歷史行情小批量回補試驗 / Bounded official history backfill pilot

## 為什麼先分離歷史回補？
- 2026-11-14 原本主分支已經持久化了 2026-11-11、12、13 三個交易日的 TWSE / TPEx OpenAPI 快照，共有最新日約1960檔有效股票；這些行情是未還原價量。
- 官方帶日期端點：TWSE 的 MI_INDEX (type=ALLBUT0999)，TPEx 的 afterTrading/otc (type=EW)。與只返回最新交易日的 OpenAPI 不同，這些網址支援指定日。
- **重要口徑差異：** TPEx 帶日期歷史端點的成交股數／金額主要為整股交易（round-lot），原本最新日 OpenAPI 則包含其他交易時段，不能直接接成同一條成交量歷史；TWSE 與 TPEx 也不是互相可比較的量口徑。
- 每日回補使用的是**目前**公司名單，無法重建過去下市公司與當時存續母體，存在存活偏誤，不得拿來宣稱全市場歷史回測勝率。

## 執行 / How to run
1. GitHub Actions／行動 → Official History Backfill Pilot → Run workflow／執行工作流程（main 分支）。
2. 預設 start_date=2026-11-04、end_date=2026-11-10；程式最多允許5個平日、15天內的日期區間，並只能查最近60天內、且**早於原本正式行情最早歸檔日**的日期。每次請求至少等待約2.5秒。
3. 使用 TWSE／TPEx 官方公司母檔，只保留公司股票，每市場至少75%公司有有效開高低收、成交股數與成交金額。不存在、資料缺值或停牌不補零；重複代號／不合理價量／來源資料日期矛盾即拒絕。
4. 保留在 data/market_backfill_pilot/YYYY-MM-DD.json.gz；一個交易日一檔；單次沒有新日期時不重複提交。
5. 每次診斷產物名 historical-backfill-pilot-status，含是否成功、實際歸檔日期／筆數／官方日期確認程度，不含私人持倉、API Token、CHAT ID 或 PAT。

## 正式選股的限制
- Backfill 是獨立的研究試驗資料，不會進入 data/market_daily，也不會被 technical_readiness.py 自動納入；其 status 固定為 historical_pilot_research_only。
- 實際回傳日期若不在官方 metadata 中，記為 query_only_unverified，不能憑請求網址宣稱已取得官方明示日期。
- 未完成與最新日 OpenAPI 的重疊樣本價量比較、除權息／減資調整、官方交易日曆、下市樣本、分時段口徑確認、籌碼及基本面之前，禁止輸出 Top10、實績勝率、買賣價。
- GitHub 網路連線、schema 及授權可能造成試驗失敗；若失敗請讀當次執行日誌及 artifact，不得用估計數據取代。

## 來源
- TWSE 官方按日 MI_INDEX： https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20261104&type=ALLBUT0999&response=json
- TPEx 官方按日盤後： https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date=2026%2F11%2F04&type=EW&response=json
- TWSE 官方公司名單： https://openapi.twse.com.tw/v1/opendata/t187ap03_L
- TPEx 官方公司名單： https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O
- 詳見 Issue #6。
