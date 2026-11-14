# 三大法人官方歷史資料來源驗證（尚未入庫）

## 背景
量化選股的籌碼占比25%，不能用最新一天 OpenAPI 假裝過去指定日期資料。2026-11-14 研究指出 TPEx 開放資料 OpenAPI 多為最新一期；若任意加 date 參數，可能不影響回傳結果。正確歷史來源應從官方帶日期的網頁報表 API 取得。

## 官方待驗證來源
- TWSE 上市三大法人 https://www.twse.com.tw/rwd/zh/fund/T86 ，date=YYYYMMDD、selectType=ALLBUT0999、response=json。外資淨額欄「外陸資買賣超股數(不含外資自營商)」不可抓成買進股數；外資自營商不應重複加入自營合計。
- TPEx 上櫃三大法人 https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade ，type=Daily、sect=EW、date=民國年/MM/DD、id空、response=json。上櫃回應可能有重複的買進／賣出欄位，不能單靠欄名轉換成字典，否則會遺失資料。

## 驗證方法
- 固定兩個已知交易日2026-11-12與13，逐市場查詢共四次，至少間隔2.5秒。
- 必須回傳合法來源狀態、非空欄位、表格每一列的長度與欄位數一致，且回報的資料筆數達到至少250筆。
- 每市場兩日期表格資料SHA256不同，才能證明不是重複返回完全相同的最新日資料；若官方有可解析明示日期則核對，沒日期則明示 query_only_unverified。
- 記錄每日期筆數、欄位名稱、重複欄名狀況和資料內容雜湊；完整行情報價及未驗證欄位數值不會在網站公開。
- GitHub Actions → Official Dated Institutional Source Probe，合併 main 後會自動執行一次，亦可手動執行。完成後下載 institutional-source-probe 研究產物。

## 尚未完成
上述探測只是檢查日期資料有變化，**不等於確認所有上市櫃公司、外資／投信／自營商欄位及其單位已正規化**。後續須針對各市場確定欄位意義、和現有日資料交叉比對、完整覆蓋與檔數去重、公告日可用性，才能建立每日歷史籌碼檔。

未來正式評分仍須加上借券、融資、TDCC、財報、除權息調整及樣本外淨績效；本階段 dataMergeAllowed=false、top10=null、publishable=false。

- 參考來源：https://www.twse.com.tw/rwd/zh/fund/T86
- 參考來源：https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/3itrade/day.html
- 開發任務：https://github.com/leon5281ss/taylorstock-dashboard/issues/6
