# TWSE 公開成交量口徑與分項證據

以下矩陣僅列可直接對應到端點的官方明文。問號表示該交易類別是否納入欄位仍待查證。

| 端點 | 欄位 | 一般交易 | 盤中零股 | 盤後零股 | 盤後定價 | 鉅額 |
| --- | --- | --- | --- | --- | --- | --- |
| STOCK_DAY | 成交股數 | ? | ? | ? | ? | ? |
| MI_INDEX 個股表 | 成交股數 | ? | ? | ? | ? | ? |
| STOCK_DAY_ALL | TradeVolume | ? | ? | ? | ? | ? |

[官方個股資訊](https://accessibility.twse.com.tw/zh/trading/historical/stock-day.html) 明示以股為單位。[官方 OpenAPI 規格](https://openapi.twse.com.tw/v1/swagger.json)、[資料字典入口](https://data.gov.tw/dataset/11549)、[MI_INDEX 報表](https://wwwc.twse.com.tw/zh/trading/historical/mi-index.html) 與 [收盤行情商品版本](https://eshop.twse.com.tw/zh/product/detail/cfec9a1470e448ec91bfde006db361e8) 仍欠缺 API 欄位至具名時段版本的官方映射。商品有 14:00、15:30、17:30 三版，零股與盤後定價、鉅額依版本納入。市場彙總的範圍無法直接套用到個股列。

[官方交易制度](https://www.twse.com.tw/zh/products/system/trading.html) 分列五類交易。以同日同代號查看分項，保留原始量，禁止將分項加回可能已包含它的總量。

- [盤中零股](https://www.twse.com.tw/zh/trading/historical/twtc7u.html) 與 [盤後零股](https://www.twse.com.tw/zh/trading/historical/twt53u.html) 的實際 JSON 均有成交股數。
- [盤後定價](https://www.twse.com.tw/zh/trading/historical/bft41u.html) JSON 使用成交數量，未直接標示單位。交易制度說明申報單位，報表欄位的單位仍待明文連結，保留原值。
- [鉅額日成交資訊](https://www.twse.com.tw/zh/trading/block/bfiauu.html) 為官方查詢入口。實測候選 JSON 路徑回傳非 JSON，三天均無可用鉅額資料。一般交易也尚缺可獨立比對的個股分項。

沿用五檔 300 筆歷史比對與原始月報，無需重新下載。以其中末三日、五檔共 15 筆進行分項檢查，12 份候選回應中 9 份通過日期與欄位解析。用下列命令擷取缺少的分項或重播已保存的回應：

```text
python scripts/audit_twse_session_components.py <證據目錄>/stockday-volume-report.json <證據目錄> --download
python scripts/audit_twse_session_components.py <證據目錄>/stockday-volume-report.json <證據目錄>
```

報告保留來源、錯誤、原始檔雜湊與每筆分項，空缺維持 null。分項相對於聚合欄位的涵蓋或重疊仍待官方映射。單一 STOCK_DAY 可提供這五檔的連續股數研究序列；尚須證明跨月口徑一致及逐檔完整，才評估量能計算。所有公開指標繼續關閉。TPEx 的 2,533 筆差異獨立追蹤。
