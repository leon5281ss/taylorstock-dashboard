# 日報操作與資料品質

## 市場政策與個股風險（PR #2）

政策不再迴圈加入每一檔股票。marketMonitor 依文章 URL 跨來源去重，獨立顯示國安基金、政府護盤、八大官股與其他政策；多主題文章只顯示於第一個主題。來源失敗仍顯示狀態，無新聞不等於沒有事件。官股買賣超仍為無權限，不補數據。

風險採透明規則而非投資評分：跌破 MA60、融資減少伴隨急跌為高；跌破 MA20、融資大增、量異常、法人連賣或有證據的相關產業新聞為中；法人連買或無已觸發警報為一般觀察。依最高規則級別，不以警報數堆疊升級。

manualCheck 重新計算為「有中／高個股警報，或核心資料非 ok／官方明確 mismatch」。官方尚未核對、規則歷史不足另外列 qualityNotices；不單獨使全市場需人工確認。資料缺漏仍可使 22 檔皆待確認，不能為了數字漂亮而移除。riskAssessment=limited 表示判斷受限；一般觀察絕不代表已確認安全。

個股只接收法人、資券、技術及具 relatedSymbols、scope=industry、來源／日期／relevanceEvidence 的相關產業新聞。此 PR 提供嚴格關聯介面，**尚未接入獨立產業新聞供應源**，公開顯示 industryNewsStatus=not_connected，不能宣稱無產業利空，也不從泛用政策關鍵字推測關聯。ETF 不推測持股穿透關聯。

Telegram 目前不發送，去重設計與啟用門檻見 [TELEGRAM_PLAN.md](TELEGRAM_PLAN.md)。新資料沿用 schemaVersion=3 並新增 riskModelVersion=1；舊快照在網站標示等待新版收集，不將舊計數當新結果。正式站要由使用者審查合併後再跑日報才更新；此 PR 不部署開發分支。

## 上線

1. 檢查 PR，核對監控名單、離線測試及 Actions；由維護者決定是否合併。
2. Repository Settings → Secrets and variables → Actions：新增 Secret `FINMIND_TOKEN`。不要放 Repository Variables、設定 JSON、GitHub Pages 或 PR。
3. Settings → Pages 的來源設為 GitHub Actions。
4. Actions → Daily Stock Report → Run workflow。選開發分支只收集與上傳公開報告，不部署 Pages；合併後選 main 才部署。
5. 查看 Job Summary 與 public-daily-report artifact；品質檔列出每檔每資料集的日期、狀態、缺漏、官方核對結果及未能計算的警報。

## 排程與非交易日

UTC 13:00／13:20／13:40（臺灣 21:00／21:20／21:40），週一至五。後兩次為延遲發布重查，會重新產生報告。GitHub 排程可能排隊，21:00 是啟動目標，不保證精準送達時間。

以 FinMind TaiwanStockTradingDate 及 TWSE 官方休市表判斷。官方休市日、一般週末標記 non_trading_day，日報使用最近已確認交易日；星期幾不能單獨證明平日有交易。颱風臨時休市若尚未反映於來源，標記 awaiting_confirmation，不擅自視為資料完整。

每次請求對 429、5xx、網路異常最多嘗試三次；401／403 等不無限重試。交易日資料未發布時，每欄保留本次 API 回傳的最新已公布日期與 delayed 標記；API 整體失敗則顯示錯誤與 null，不把舊值冒充當日值。跨次 API 全面失敗目前不恢復上次 artifact。非交易日仍可執行產生有標記的最近日報。

## 資料、單位與核對

| 類別 | FinMind 資料集 | 單位／規則 |
|---|---|---|
| 價量 | TaiwanStockPrice | 元、股；非還原價 |
| 法人 | TaiwanStockInstitutionalInvestorsBuySell | 股；買進－賣出 |
| 融資融券 | TaiwanStockMarginPurchaseShortSale | 張；當日餘額－前日餘額 |
| 官股 | TaiwanStockGovernmentBankBuySell | register 無權限，永遠不填 0 |

外資合計 Foreign_Investor + Foreign_Dealer_Self；自營商合計 Dealer_self + Dealer_Hedging。本版收集近 240 個日曆日，不支援 2017 年以前法人舊分類回測。缺少應有分類時是 null，不能當成沒有交易。

TWSE 日期指定 MI_INDEX（失敗時回退 STOCK_DAY_ALL 快照）、TPEx daily_close_quotes 核對價量；TWSE 日期指定 T86、MI_MARGN，TPEx 3insti_daily_trading、mainboard_margin_balance 核對法人與資券。官方原始值優先作核對依據，同日期價格容許 0.005 元誤差，股數／張數必須一致。差異保留雙方數值，標記 mismatch 並停止該類警報計算，不悄悄覆蓋。官方快照可能晚於或早於查詢日期，日期不一致標記 unverified，不宣稱核對成功。

官方核對主要涵蓋最新回傳日；FinMind 歷史資料不宣稱逐日獲官方驗證。來源無回應、欄位改名、未發布都會在 quality.json 顯示。官方休市表須覆蓋查詢年；否則停用依賴完整交易日序列的警報。

富喬（1815）市場別已依 TPEx 官方行情修正為 TPEX。00685L 是槓桿 ETF，00981A 是主動 ETF；同樣收集實際有回傳的價量與籌碼，不要求公司 EPS、營收或毛利率。融資融券缺資料時維持 missing，未經官方資格確認不擅自標成零或不適用。

## 警報定義

| 規則 | 觸發條件 |
|---|---|
| 外資／投信連續買賣超 | 最近至少 3 個連續交易日同方向，零與缺日中斷 |
| 融資大增 | 單日增加至少 10% 且至少 100 張；前日餘額須大於零 |
| 融資減少伴隨急跌 | 融資日變化 < 0 且收盤日跌幅 ≤ -5% |
| 跌破 MA20／MA60 | 前日收盤 ≥ 前日均線，今日收盤 < 今日均線 |
| 成交量異常 | 當日量 ≥ 前 20 交易日平均量兩倍，或 ≤ 0.5 倍 |
| 政策消息 | 財政部、國安基金、金管會官方標題關鍵字命中，日期可解析且在最近七日 |

缺日、缺欄位、歷史長度不足、官方核對差異均會阻止相應計算；unavailableRules 必須與 alerts 一起閱讀。使用非還原價，除權息、分割等可能造成機械式跌破／急跌，須人工核對。政策項目是候選公告，非已確認重大利空或護盤進場；無日期公告列在政策追蹤區但不當作新警報。官方頁面解析失敗標記失敗，不寫成「沒有新聞」。同一七日窗口的公告會重複顯示，不發送交易或私人訊息。

## 八大官股待接入

目前依已驗證 register 權限設定停用，顯示「無權限」。模組可明確啟用重新查詢，但即使回傳資料也先標記 adapter_pending；須完成 Sponsor 權限、數量／金額單位與彙總列驗證後才接入數值。八大官股合計不可再與八家個別列相加。國安基金政策消息與官股買賣資料分開處理。

## 隱私與私人損益

公開流程僅讀取 watchlist_public.json 的代號、名稱、市場、分類及商品類型。不讀 Excel、positions_private.json 或任何私人持倉。公開資料、日報、Pages 與 Actions artifact 都不含持股數、成本、持倉與損益率；本版全面取消舊的固定分數。

私人估計平倉損益函式位於 scripts/market_pipeline/private_pnl.py，只供離線呼叫，公共流程不匯入它。呼叫者必須提供買賣手續費率、最低手續費及適用商品／日期的證交稅率，不由股票名稱猜稅率。計算：賣出價款－賣出手續費－證交稅－買入價款－買入手續費；成本輸入應為未含手續費均價。費用以元四捨五入，是估計值，實際對帳應使用券商成交費用；不包含股利、借券費與融資利息。不要把真實持倉當測試資料或上傳 artifact。

## 本機驗證

```text
python -m unittest discover -s tests -v
python -m compileall -q scripts
python scripts/validate_public.py
node --check docs/assets/app.js
python scripts/probe_official.py
```

最後一項是無 Token 的唯讀連線測試，會查官方資料及公開交易日，可能需要網路權限。離線測試的虛構數據只在測試記憶體及暫存目錄，絕不作為公開範例報價。版本庫內的 stocks.json 為 22 檔 null 初始化狀態；首次 Actions 成功後才會在部署 artifact 產生真實資料，不提交市場數據到 main。

FINMIND_TOKEN 缺失時程式退出 2，避免把舊資料當成功新報告；其他致命錯誤退出 1，僅輸出安全錯誤類別。取得部分資料時正常產生 partial 報告，明確保留缺漏。完整 22 檔報告指每檔都有列，不代表所有來源在 21:00 必然已發布。

## HTTP 診斷與失敗門檻（PR #1 修正）

先在 feat/finmind-daily-22 執行 FinMind 2303 Cloud Smoke（修改來源或診斷程式時自動觸發，亦可手動執行）。只查聯電最近 15 日至昨日的價格、法人、資券及交易日，遇第一項失敗即停止；價格失敗時最多追加一次相同參數的匿名對照，不將匿名資料當成正式日報。每日工作流程亦先做此預檢。

認證維持 HTTP Authorization Bearer，Token 不進 URL。診斷只保留資料集、日期、列數、固定錯誤分類及 HTTP/API 狀態碼；不輸出回應原文、標頭、Token 片段或私人資料。HTTP 200 內的 API 失敗也會被攔截。

| 分類 | 處理 |
|---|---|
| invalid_token / token_format_error / missing_token | 至 GitHub Settings → Secrets and variables → Actions 更新 FINMIND_TOKEN；只填 Token，不加 Bearer、引號或換行。不要貼到聊天、Issue 或程式碼。 |
| permission_denied | FinMind 會員權限不足；核對帳戶及資料集方案，不用假值補齊。 |
| invalid_parameters | 檢查 dataset、data_id 與日期，不盲目重試。 |
| rate_limited | 402 配額耗盡停止；429 有上限退避重試並尊重數字 Retry-After（最多 60 秒）。 |
| network_error / server_error | 有上限退避重試，仍失敗則標記，不輸出底層例外。 |
| ip_blocked / access_denied / bad_request | 分別代表封鎖、未能確認原因的拒絕及未能分類的 400；不可直接推論為 Token 無效。 |

Token 無效、IP 封鎖或配額耗盡會中止同一 client 後續認證呼叫，避免 22 檔重複無效請求。依 [FinMind 官方封鎖政策](https://finmind.github.io/BanIPPolicy/)，認證或權限錯誤不應反覆重試。

任一核心資料類別（價格、法人、資券）全 22 檔皆無可用記錄時，reportStatus=failed 並退出 1；不再以 partial 掩蓋全面失敗。零檔完全齊備但各類仍有延遲有效記錄時可為 partial，保留個別日期及缺漏。官方核對、投信差異與 ETF 缺值規則不變。

當次輸出先寫入 run-output/，僅收集成功才複製至 Pages 資料目錄。失敗保留安全診斷與當次品質報告 artifact，不發布失敗資料，也不把版本庫舊檔當本次結果。預檢失敗時尚未收集 22 檔，因此只會有診斷 artifact，沒有偽造的完整日報。

## 參考規格

- [FinMind 官方籌碼 API](https://finmind.github.io/tutor/TaiwanMarket/Chip/)
- [TWSE OpenAPI](https://openapi.twse.com.tw/)
- [TPEx OpenAPI](https://www.tpex.org.tw/openapi/)
- [財政部 RSS](https://www.mof.gov.tw/Rss)
- [國安基金官方新聞稿](https://www.mof.gov.tw/multiplehtml/383)
- [金管會官方新聞稿](https://www.fsc.gov.tw/ch/home.jsp?id=96&parentpath=0,2)
