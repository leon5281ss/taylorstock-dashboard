# TDCC外部歷史週快照與官方資料來源比對

## 緣由
TDCC官方 dataset 1-5 提供最新每週的集保戶股權分散資料；官方不保證可由同一URL回查每個歷史週。公開GitHub備份 wirelessr/tdcc-opendata-archive 目前有2026年4月底至11月的週資料，但這些文件是**第三方備份**，不能未經核對就宣稱是當時官方可取得資料。

來源：
- TDCC官方 https://opendata.tdcc.com.tw/getOD.ashx?id=1-5
- 外部歷史備份 https://github.com/wirelessr/tdcc-opendata-archive
- 官方每週原始資料在主庫的 data/tdcc_weekly_research/YYYY-MM-DD.json.gz

## 本階段可自動做的事
- 取本庫中最新已驗證官方週快照（例如2026-11-13），使用同日期的外部CSV備份檔。
- 使用同一套TDCC17級、日期、總股數及現行上市櫃公司名單檢核。
- 只比對同公司代號、同市場的6種指標：人數總和、集保總股數、第15級持股及百分比、第16級差異調整等。
- 最低需1000家共同比對、且涵蓋官方驗證公司至少95%。若不一致占比超過0.1%則整批拒絕；保留差異數及至多10個代號供稽核。
- GitHub Actions → TDCC External Weekly Archive Crosscheck；首次合併後跑一次，或手動啟動。只讀來源，不會把外部資料保存到正式TDCC研究檔案。

## 重要邊界
即使最新一週全數一致，也**不能推論2026年更早的每一週備份都沒有改動、遺漏、重新上傳或資料日期錯誤**。本模組固定 mirrorHistoryAuthorizedForFactorUsage=false、top10=null、publishable=false。後續若需要歷史回補，應逐週進行來源SHA256、回應年份、資料品質及發布時點檢查，區分外部備份與TDCC官方原始取得的週資料。
