# 全市場官方每日價量歷史庫 / Official daily OHLCV archive

## 範圍與可靠性
只收集上市與上櫃普通公司股票的官方收盤未還原 OHLCV。使用既有 TWSE / TPEx 公司母檔過濾 ETF、ETN、權證與非公司證券。僅含公開行情；不含私人持股、成本、Telegram Chat ID、PAT 或憑證。

官方來源：
- TWSE STOCK_DAY_ALL：https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL
- TPEx tpex_mainboard_daily_close_quotes：https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes
- 上市、上櫃公司母檔：參見 docs/QUANT_SCREEN.md

兩個 OpenAPI 主要提供最新交易日快照，不提供任意歷史區間。每天保存快照不代表已有 121 日或多年下市樣本；日線仍需除權息、減資與停牌校驗。

## 執行與持久化
- GitHub「Actions／行動 → Official Daily Market History → Run workflow／執行工作流程」，分支 main。
- 預設台灣交易日 22:50，與隔日上午 09:15 備援；GitHub 排程可能延遲。
- 新資料寫入公開庫 data/market_daily/YYYY-MM-DD.json.gz，檔名取自官方資料的實際交易日，而非 GitHub 執行日期。
- 每次執行保存 market-history-status artifact（30天），含來源、各市場資料筆數、母檔覆蓋數、歸檔名稱或失敗原因。
- github-actions[bot] 只提交 data/market_daily，不觸及私人帳本。相同內容重跑不重複提交。若分支保護規則拒絕推送，執行會明確失敗，不宣稱已保存。

## 嚴格門檻
- 官方上市公司至少1,000檔、上櫃至少700檔；禁止跨市場重複代號。
- 僅收公司名單內的股票；每市場有至少80%公司具完整合法的開高低收、成交股數及成交金額。
- 官方單市場日期一致，兩市場日期一致；日期不得為未來或比今日早超過4個日曆日。
- 不補零、不插值；停牌無報價、缺漏價格、負值、OHLC矛盾或重複股票代號明確拒絕或剔除。
- 不合格或資料源失敗時不提交新檔。未經還原的 OHLCV 不能直接作為實際跨除權息報酬或可成交依據。

## 尚未完成（Issue #6）
- 至少121交易日完整回補、下市公司、官方交易日曆與除權息校正。
- MA5/20/60/120、RSI14、MACD、動能及波動度的完整技術特徵歷史。
- 法人／融資／借券／TDCC，五年EPS／ROE／營收、估值與發布時間。
- 通過資料完整性、樣本外回測、費稅及滑價後才可能發布 Top10 和 Telegram 選股提醒。

這項改動不會下單、不會把公司母檔股票誤報成完整量化選股，也不會改動既有22檔 Telegram 風險通知。
