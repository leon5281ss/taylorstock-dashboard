# TWSE 成交股數口徑研究

查核日期為 2026-11-15（臺灣時間）。「未知」表示缺少公開文件把該來源的欄位對應到特定交易類別。

| 來源 | 實際欄位 | 一般交易 | 盤中零股 | 盤後零股 | 盤後定價 | 鉅額交易 |
| --- | --- | --- | --- | --- | --- | --- |
| 個股月報 STOCK_DAY | 日期、成交股數 | 未知 | 未知 | 未知 | 未知 | 未知 |
| 歷史日報 MI_INDEX 個股表 | 證券代號、成交股數，外層 date | 未知 | 未知 | 未知 | 未知 | 未知 |
| 每日 OpenAPI STOCK_DAY_ALL | Date、Code、TradeVolume | 未知 | 未知 | 未知 | 未知 | 未知 |

- [TWSE 個股日成交資訊](https://accessibility.twse.com.tw/zh/trading/historical/stock-day.html) 明示單位為元、股。資料自 2010-01-04 起提供，頁面未標示文件發布日期。
- [TWSE 每日收盤行情](https://wwwc.twse.com.tw/zh/trading/historical/mi-index.html) 展示成交股數及多張統計表。頁面未標示文件發布日期或把個股列連結至特定盤別。
- [個股日成交資訊資料集](https://data.gov.tw/dataset/11549) 於 2017-05-23 上架，官方詮釋資料更新於 2025-05-01。列出日期、代號及成交股數，並連到 [TWSE OpenAPI](https://openapi.twse.com.tw/v1/swagger.json)，尚缺逐盤別欄位定義。
- [TWSE 每日收盤行情商品規格](https://eshop.twse.com.tw/zh/product/detail/cfec9a1470e448ec91bfde006db361e8) 明列 14:00 版含一般交易，15:30 版加入零股及盤後定價，17:30 版再加入鉅額。規格有標記部分格式生效日期，也列出資料自 2003-12-01 起提供。頁面未標示發布日期，也沒有把以上三個公開端點逐一映射至商品版本。零股分類未在商品頁拆成盤中與盤後。
- [TWSE 集中市場交易制度](https://www.twse.com.tw/zh/products/system/trading.html) 分列一般、盤中零股、盤後零股、盤後定價及鉅額交易制度。頁面未標示發布日期。

## 同日股數對照

截至 2026-11-13 的官方日曆窗口共 60 個交易日。沿用 2317、2330 的 8 份月報，另擷取水泥、塑化及金融樣本 1101、1301、2881 的 12 份月報。五檔各 60 日均相符，合計 300 筆，其中 120 筆為原有樣本。各日比較使用該日已歸檔的 MI_INDEX 或每日 OpenAPI；只有末三日使用每日 OpenAPI。

重播指令為 `python scripts/compare_twse_stockday_volume.py <證據目錄> --codes 1101 1301 2317 2330 2881`。證據目錄保存 20 份官方原始回應、逐檔來源 URL、SHA-256 及稽核報告。

各端點的盤別映射尚待官方版本證據或可重現的分項驗證。已通過口徑驗證 0 檔。TPEx 仍有 2,533 筆差異未驗證，1,869 筆零股算術吻合，664 筆有殘差。研究維持 V5/V60=null、top10=null、publishable=false。
