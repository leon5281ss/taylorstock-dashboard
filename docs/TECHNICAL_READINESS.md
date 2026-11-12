# 歷史價量技術指標準備度 / Technical archive readiness

目的：讀取 data/market_daily/YYYY-MM-DD.json.gz，統計已累積交易日數、最新有報價股票數與可以使用完整 121 個歸檔交易日計算技術指標的股票數。

工作流程：GitHub Actions → Technical Archive Readiness → Run workflow（手動），或 Official Daily Market History 成功後自動觸發。只讀取主分支公開歷史行情，產生技術準備度 Artifact，不提交檔案、不發 Telegram、不動用私人倉位或下單。

輸出：
- archivedTradingDays / daysUntil121：累積日數與距 121 天的差額，**不是回測樣本量**。
- technicalCompleteCount：最新交易日持續有報價，且具備最近 121 個歸檔交易日的股票數。
- rawTechnicalResearch：研究用 MA5、MA20、MA60、MA120、RSI14、MACD histogram、5/20日動能、20日波動度、20日平均成交金額。
- top10 永遠 null；publishable 永遠 false。

資料品質：每檔 gzip 實際日期必須與檔名一致；只接受 schemaVersion=1 和 raw_unadjusted；每市場代號不可重複；驗證 OHLC 價格、量、成交值及市場筆數。全市場 trading dates 按已歸檔日期排序；如果一檔股票未涵蓋最近 121 個檔案的全部日期，則不列為技術資料完整。

**重要限制**：這只是未還原行情上的技術研究指標，遇除權息、減資、換股或缺漏可能大幅失真。即使 technicalCompleteCount 大於 0，也不能輸入 35/25/25/15 正式模型的 verified 因子或發布選股排名。需先完成點時點除權息、五年財報、三大法人、融資／借券及 TDCC，再做樣本外淨績效回測；詳見 Issue #6。

首次歷史歸檔（2026-11-11）有 TWSE 1088 與 TPEx 872，有效合計 1960。僅一個交易日的情況下，技術完整數預期是 0；這不表示 1960 檔股票不值得投資，只是尚未累積足夠的可靠技術歷史。
