# 自動研究價量覆蓋率稽核 / Research-only Price Coverage Audit

## 用途
自動讀取 data/market_daily 的官方最新行情及 data/market_backfill_pilot 的按日期歷史試驗行情，僅用股票代號、日期及**開高低收的存在與有效性**來統計研究資料涵蓋狀態。程式**不融合成交股數／成交金額**；上櫃歷史整股交易與官方最新日 OpenAPI 交易時段口徑不相容。

## 自動執行
- 在 PR 第一次合併進 main 時自動測一次。
- 往後 GitHub Actions「Automatic Research History Backfill」成功後自動產生新的覆蓋率稽核結果。
- 手動可選 Actions → Research Price History Coverage → Run workflow（main）。
- 每次產出 30 天保留的研究 Artifact：research-price-coverage / research-price-coverage.json。

## 指標與品質閘門
- productionDays：官方最新日永久保存的獨立交易日期數。
- historicalResearchDays：官方帶日期研究資料的日期數。
- totalObservedDates：兩者日期聯集；只代表曾觀測到的日期，**沒有完成台灣證交所與櫃買中心歷史交易日曆認證**。
- pricePresenceByWindow：5、20、60、121 個已保存日期窗口內，各股票都存在 OHLC 的上市與上櫃檔數。只是價位可見性，不能保證沒有除權息、減資或斷期錯誤，沒有籌碼／基本面可用性。
- historicalSourceDateNotExplicitCount：歷史來源沒有明示交易日期的歸檔日數，須繼續核對，不能把查詢網址當成完整日期證據。
- 若同日同時存在兩種不同來源檔案、成交價非法、檔名與交易日不一致、研究價格量口徑標記有誤，稽核拒絕整個結果。

## 禁止誤用
即使研究價位日期數超過121天，仍然維持：corporateActionAdjusted=false、historicalPointInTimeUniverseAvailable=false、fullFactorDataReady=false、verifiedBacktestAvailable=false、top10=null、publishable=false。

這個稽核不會發買賣通知、不會修改主分支正式行情、不會自動下單。完成歷史除權息、當時市場母體、官方完整交易日曆、外資投信／融資借券／TDCC、財報與估值時間點資料及扣費稅滑價回測，才可以放行真實選股驗證。

追蹤：[Issue #6](https://github.com/leon5281ss/taylorstock-dashboard/issues/6)。
