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


## 取得原始證據與重播

原始回應及本機報告未提交。GitHub CI 執行程式測試，五檔 300 筆及新增 12 份回應的雜湊驗收在本機執行。

在儲存庫根目錄使用全新的證據目錄，執行：

```text
python scripts/compare_twse_stockday_volume.py twse-evidence --codes 1101 1301 2317 2330 2881 --download
python scripts/compare_twse_stockday_volume.py twse-evidence --codes 1101 1301 2317 2330 2881
```

下載模式逐次間隔至少 2.5 秒，保存原始回應與來源清單。重播會核對 SHA-256、URL、月份、代號、交易日期及成交股數欄位；已存在的證據不會重新下載。若日後官方修訂回應，另存新證據並檢查差異；下列雜湊對應本次留存的版本。

| 原始檔 | 官方來源 | SHA-256 |
| --- | --- | --- |
| stockday-1101-2026-08.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260801&stockNo=1101&response=json) | `6a940ded44b56b9728157834b6ba98f487df8960040623c9bcf713fd1b0aad8b` |
| stockday-1101-2026-09.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260901&stockNo=1101&response=json) | `940808b14a658103aacd5a7b430c65406fcad646e25e420a688984bdb8eb2ab0` |
| stockday-1101-2026-10.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20261001&stockNo=1101&response=json) | `84cce8cb0059a2207c6ffb39ae837b85663eda8f634ac503ff2f23d2f6eeb097` |
| stockday-1101-2026-11.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20261101&stockNo=1101&response=json) | `848f43e0b27ebac574871ebb6d0581585d25a12d8675524dc66351b6d2e8c200` |
| stockday-1301-2026-08.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260801&stockNo=1301&response=json) | `e70a52b0b1abffa5cad248aaaef0159ab133435abc4c027334a3dafbb3d9be4b` |
| stockday-1301-2026-09.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260901&stockNo=1301&response=json) | `f44f1678dfd7c40e119aa88ce2ca16086f686b553fdd045129768ba8a9eaa464` |
| stockday-1301-2026-10.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20261001&stockNo=1301&response=json) | `63e175de069aa7d71fd24240ce3a93c81e8cf84c59c1f5dba2304b960e3441b7` |
| stockday-1301-2026-11.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20261101&stockNo=1301&response=json) | `18500bba3cdb7e60d7af29ee6048d325cbe97219d38c68b5536f1633432a261d` |
| stockday-2317-2026-08.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260801&stockNo=2317&response=json) | `8b50281bedd07ae6628e9f7b504bb048ecff915712eae6845f529b286a070682` |
| stockday-2317-2026-09.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260901&stockNo=2317&response=json) | `ac4ef2ac4395462d02cabac81c5ca7c23b1902c732e5873dd3eeb4d5708d2800` |
| stockday-2317-2026-10.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20261001&stockNo=2317&response=json) | `64ec7a495aac3de46234237aa5321c3bae34010f07cea4e98894744813dd86a8` |
| stockday-2317-2026-11.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20261101&stockNo=2317&response=json) | `5ad13f7d04748891b4c2673aa84bad75d1e7bd71fe75299b82d6ecfe42c6cf44` |
| stockday-2330-2026-08.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260801&stockNo=2330&response=json) | `017e038130832238b1241583681f2beec016a7241bc77d1a62fadcc4aa9f0f38` |
| stockday-2330-2026-09.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260901&stockNo=2330&response=json) | `c556fb917676d81615b5c8e133c5f36dae52fba2efcfc8b9ab196c86ef1506ec` |
| stockday-2330-2026-10.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20261001&stockNo=2330&response=json) | `9ea034f6a419f13e8dcfe5c99edfce8137bcdb52d5f3a5d0002fee8a1ddc960a` |
| stockday-2330-2026-11.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20261101&stockNo=2330&response=json) | `9442564d6fc5f850c0d0e0834cf0d4afbdad9c3d34a48b8aa6e3d3ef91d386ee` |
| stockday-2881-2026-08.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260801&stockNo=2881&response=json) | `65e3d3b3553dd0e52d5cca823ab3a466f2ce5bc4f0836fce0df5f16714e4b326` |
| stockday-2881-2026-09.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20260901&stockNo=2881&response=json) | `9649296374fdfe69f107b382f7356a4e434420ff7cd56b7b7f7c599ad32cd6f3` |
| stockday-2881-2026-10.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20261001&stockNo=2881&response=json) | `75082fdedb9396cc9532e3287c9d46a453e655d808f6f1eebcfce20d6940a66d` |
| stockday-2881-2026-11.json | [TWSE](https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20261101&stockNo=2881&response=json) | `ef30bb2703f19d1376d859903001cf0e6153bf4259996e170f812f9704d6fdc7` |
