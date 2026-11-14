# 官方歷史行情與每日行情交叉核對

## 目的
PR #7 已自動保存未還原的上市／上櫃全市場官方日行情。PR #9 另建立獨立的帶日期歷史試驗資料，但上櫃帶日期端點主要反映整股交易，最新 OpenAPI 含其他交易時段，成交量不能直接混合。

本稽核只針對 data/market_daily 已保存日期，重新查詢官方指定日歷史端點，比對同一股票代號的開高低收、成交股數和成交金額，不會直接合併歷史資料庫，不會自動產生 Top 10。

## 執行
GitHub「行動 / Actions → Official Historical Source Consistency Audit → Run workflow / 執行工作流程」，分支 main。也會在稽核程式合併 main 時自動跑一次。

每次只查最新2個已保存交易日（最多3個），每次官方請求間隔2.5秒。產物：cross-source-history-audit.json（保留30天），不使用任何金鑰。

## 指標
- sharedSymbols：同代號同市場、兩種官方來源共同有報價的股票數（上市至少700檔，上櫃至少500檔）。
- ohlcMatchRate：開高低收容差0.011元內全部相符的股票比例，附最多12個不一致範例。
- volumeExactMatchRate / turnoverExactMatchRate：成交量與成交金額完全相同的比例。
- datedToLiveMedianVolumeRatio / datedToLiveMedianTurnoverRatio：歷史口徑／即時OpenAPI口徑的中位比率，僅用來偵測來源口徑差異。
- sourceDateEvidence：只對有官方回傳日期且吻合請求日期者標示 explicit_response_date，否則記 query_only_unverified。
- historicalVolumeCompatible：僅在上市 TWSE 成交量、金額比對均達98%相等時為真；上櫃一律為false，禁止直接混入。
- integrationAllowed 永遠為 false，top10=null，publishable=false。

## 明確尚未完成
除權息、減資調整、歷史母體／下市公司回補、官方交易日曆、基本面與籌碼 point-in-time 日期驗證、淨報酬回測。即使 OHLC 相符率達99%，也**不代表**歷史資料已能提供可信選股勝率。

## 資料來源
- TWSE 按日 https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX
- TPEx 按日 https://www.tpex.org.tw/www/zh-tw/afterTrading/otc
- 每日官方資料與原始歸檔詳見 docs/MARKET_HISTORY.md 與 docs/BACKFILL_PILOT.md。
