# 官方除權息參考事件研究資料（尚未還原股價）

## 目標
全市場量化回測不能把除權息跳空當作真實損失，亦不能把官方「除權息參考價」直接當成現金股利再投資的總報酬。我們先建立兩個市場的官方除權息參考事件資料庫，保留尚未解決的資料缺口，不投入正式買賣模型。

## 官方來源
- 上市 TWSE 除權除息計算結果表 TWT49U：https://www.twse.com.tw/rwd/zh/exRight/TWT49U ，使用 GET，帶 startDate/endDate 的 YYYYMMDD、response=json。
- 上櫃 TPEx 除權除息計算結果 exDailyQ：https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ ，使用 POST 表單 startDate/endDate 的 YYYY/MM/DD、id 空字串、response=json。
- 只保留目前官方上市／上櫃公司名單的四碼普通公司代號；不含 ETF／ETN／權證，但**不能修正過去已下市公司存活偏誤**。

## 研究內容與驗收
- 從台北當年1月1日到當日，正規化「資料日期／除權息日期、股票代號、除權息前收盤價、除權息參考價、權／息」欄位。
- 根據來源欄名而非欄位順序正規化日期、價格及事件種類；來源格式異常、無事件、價位錯誤、日期超界、同股票同日重複、TPEx totalCount 與資料筆數不一致則拒絕歸檔。
- 每次輸出每市場事件數。通過驗證才寫入 data/corporate_action_research/YYYY.json.gz，並上傳30天的 corporate-action-reference-status 診斷。
- GitHub Actions → Official Corporate Action Reference Research：首次程式合併後自動執行，往後週一至週五台灣時間23:15更新，亦可手動 Run workflow。
- 官方除權息來源仍**沒有涵蓋全部現金股利總報酬、減資／分割／股票拆併或歷史下市公司**。沒有配股率、每股現金股利完整事件資訊時，不能假設 referencePrice / previousClose 就是可交易且正確的調整因子。

## 禁止誤用
資料狀態固定為 corporate_action_reference_research_only、adjustedOhlcvReady=false、referenceRatioIsNotTotalReturn=true、cashDividendTotalReturnCorrectlyModelled=false、capitalReductionAndSplitCoverage=false、historicalPointInTimeCompanyUniverse=false、top10=null、publishable=false。

**這個研究模組不能輸出買賣建議，不能據此宣稱計算真實策略勝率，也不會修改任何正式股票收盤行情、私人持倉或 Telegram 設定。**

待完成：配股／現金股利完整權益、減資／分割與復牌事件、歷史公司成分、交易日曆、因子入庫與符合發布日期的樣本外扣費稅回測。追蹤 Issue #6。
