# TWSE 公開端點口徑待核與官方詢證

目前的證據矩陣以「納入」「排除」「待官方確認」表示同一欄位是否涵蓋該類交易。

| 報表或版本 | 一般 | 盤中零股 | 盤後零股 | 盤後定價 | 鉅額 |
| --- | --- | --- | --- | --- | --- |
| STOCK_DAY 成交股數 | 待確認 | 待確認 | 待確認 | 待確認 | 待確認 |
| MI_INDEX 個股表成交股數 | 待確認 | 待確認 | 待確認 | 待確認 | 待確認 |
| STOCK_DAY_ALL TradeVolume | 待確認 | 待確認 | 待確認 | 待確認 | 待確認 |
| 14:00 AWSTIU／BFIGUU | 納入 | 排除 | 排除 | 排除 | 排除 |
| 15:30 AWSTIU1／BFIGVU | 納入 | 零股合列 | 零股合列 | 納入 | 排除 |
| 17:30 TWTA6U／BFIGWU | 納入 | 零股合列 | 零股合列 | 納入 | 納入 |

官方商品規格僅對商品版本聲明範圍。15:30 與 17:30 文案未逐項拆分盤中和盤後零股。三個公開端點與商品版本的映射均未查獲。[商品規格](https://eshop.twse.com.tw/zh/product/detail/cfec9a1470e448ec91bfde006db361e8) · [OpenAPI 規格](https://openapi.twse.com.tw/v1/swagger.json)

- BFT41U 公開欄位為「成交數量」。官方交易制度說明申報單位，行情傳輸手冊另有定價交易數量的單位規格，兩者尚未直接連結到 BFT41U 的欄位。保留原值。[交易制度](https://www.twse.com.tw/zh/products/system/trading.html) · [盤後定價報表](https://www.twse.com.tw/zh/trading/historical/bft41u.html)
- BFIAUU 可按日查詢。有效 JSON 路徑為 https://www.twse.com.tw/rwd/zh/block/BFIAUU ，以 date=YYYYMMDD、response=json 查詢。2026-11-11 至 13 實測取得標題為「單一證券」的三份報表，成交欄位明示為股數。三日分別有 21、31、18 筆成交，每日另有一列總計，股數及金額均與明細一致。程式保留逐筆成交與登錄的原始回應雜湊；股票組合與聚合行情涵蓋仍待查證。[鉅額日成交資訊](https://www.twse.com.tw/zh/trading/block/bfiauu.html)
- 五檔既有 300 筆證據維持原樣。STOCK_DAY 單源的 60 日股數可作研究序列，仍缺歷史欄位語意、版本與適用日期。先核對跨月報表版本、原始檔、交易日與公告修訂紀錄，再評估產生候選指標。股票組合鉅額、盤後定價及零股均不加回任何已聚合欄位。
- TPEx 的 2,533 筆差異獨立追蹤。V5/V60=null、top10=null、publishable=false。

## 待送官方查詢

可向 [證交所網路資訊商店盤後資訊窗口](https://eshop.twse.com.tw/zh/product/detail/cfec9a1470e448ec91bfde006db361e8) 詢問以下三項，並保存回覆日期、案件號碼與附件版本。此處為待送內容。

1. STOCK_DAY、MI_INDEX 個股表、STOCK_DAY_ALL 的成交股數各納入哪些交易類別？請分列一般、盤中零股、盤後零股、盤後定價、單一證券鉅額及組合鉅額。
2. 三個端點各對應哪個商品檔或產製時間？2026 年 8–11 月期間有無版本或歷史回補差異？
3. BFT41U「成交數量」的單位為股或證券交易單位？BFIAUU 的單一證券及組合資料如何避免重複，哪些已計入前述聚合欄位？
