# 官方除權息事件與研究價位一致性核對

## 目的
全市場日行情研究資料目前為未還原開高低收，官方除權息事件已有2026年上市及上櫃共1619筆參考事件。若遇除權息日期，**前收盤價與參考價格不等同**，不能把除權息基準價差直接當作股票價格下跌或策略失效。

## 驗證程序
獨立讀取 data/market_daily、data/market_backfill_pilot 與 data/corporate_action_research。官方除權息參考事件包含 exDate、previousClose、referencePrice、referenceRatio 與事件種類。

僅對研究歷史行情已涵蓋的事件，找出該事件日之前最近一個已歸檔官方交易日期的同市場、同股票代號未還原收盤價；在最多7日間隔內比較是否與事件表的 previousClose 一致（容差0.011元）。未歸檔事件日、缺前一筆公司價格或不一致者分別記錄，不自行補寫資料，不修改原價量，不推算現金股利。

輸出官方事件總數、已涵蓋事件數、可比較數、相符數、缺資料數及最多20筆差異示例。資料重疊、來源格式錯誤、事件元資料狀態不明則拒絕。

## 不可誤解的結果
即使兩來源的前收盤價完全一致，**也不代表已建立可交易的除權息調整係數、股利再投資總報酬或減資／分割修正**。尚缺完整歷史公司母體、當時可用財務資訊、股票拆併、減資及週期事件的即時揭露確認，且未扣交易費稅滑價計算樣本外績效。

本報告始終 corporateActionsCheckedForTrading=false、priceSeriesAdjustedForCashAndStockDividends=false、top10=null、publishable=false。它只用於確認市場資料源的前收盤口徑與資料完整性，不產生買賣訊號。

在 GitHub Actions → Corporate Event and Historical Price Crosscheck 可以手動執行；整合主分支時自動實測一次。
