# 量化策略每週複查與每日推薦稽核

## 五套候選，不是台股已驗證勝率
來源與候選參數請查看 config/quant_strategy_candidates.json。已查得海外股票籃子歷史回測五套：RSI14（81%、211筆）、MFI14（75.8%、182筆）、SMA20下方2%反彈（72.1%、1794筆）、CCI20（71.4%、1117筆）、布林通道（71.3%、988筆）。截至2026-11-12研究；來源 MarginPad，不能直接宣稱台股達到這些勝率，也無從證實為全球最高。

ChatGPT 已建立每週一晚間的公開策略研究複查任務。會搜尋更新、樣本外資料、費稅與回撤，僅提出建議而不自動更改正式策略。

## 真實每日推薦稽核規則
每天正式產生推薦時，必須事先把選股與選擇時間封存成不可變更的 JSON 訊號（存入使用者私人 GitHub 交易研究庫），至少有 selectionDate、publishedAt（+08:00）、code、strategyId、strategyVersion、horizon（5或20交易日）、shares（模擬股數）、source。
推薦當晚21:00發布，不可倒填當日收盤價當作實際進場；隔一個官方交易日開盤價才模擬進場，持有至第5或20個交易日的收盤價。無成交價、還原校驗不足、未到期時為待核實，不算成勝負。
買進與賣出估算元大股票手續費0.04275%，一般股票賣出證交稅0.3%，逐筆整元。以實際費用為最終優先；本版不含滑價、漲跌停買不到及配息，故仍非完整實際績效。
每個策略版本／持有期獨立計算成熟樣本勝率、Wilson 95%信賴區間、淨報酬、失敗因素。只有台股樣本外、已驗證參考勝率可用來判斷是否劣化；海外宣稱勝率不得填入台股預期。少於100筆平倉樣本不能宣布策略失效。
異常解釋包含：價格跌幅（price_decline）、費稅吃掉毛利（fee_tax_erased_profit）、大幅負報酬（large_adverse_move）、輸入資料品質（weak_input_quality）；後續需加上漲跌停、滑價、盤勢、產業及公告時點分析。

## 如何執行 / How to run
準備3份私人 JSON：訊號陣列 signals.json、官方依日期排序交易日 calendar.json、每股除權息已核驗OHLC prices.json。這些檔案不應放進公開 repo。
從 GitHub PR #5 的 scripts/audit_recommendations.py 使用：
python scripts/audit_recommendations.py --signals private/signals.json --calendar private/calendar.json --prices private/prices.json --output audit-output
輸出 recommendation-audit.json；未成熟或缺資料不虛構勝率。

## 目前不可宣稱已自動完成
PR #5 還沒有完成台灣全上市櫃完整歷史資料管線、每日 Top10 實際發布、每日推薦不可變更私有帳本、自動抓取官方開盤/收盤價或線上到期稽核排程；因此目前沒有可據實計算的真實每日推薦勝率。接下來要逐步接上這些資料來源與持久化機制，完成樣本外回測與當日發布的紙上交易，再評估能否啟用自動推薦。
