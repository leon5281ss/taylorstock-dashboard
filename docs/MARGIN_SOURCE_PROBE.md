# 官方上市櫃融資融券歷史來源查驗（尚未建立量化因子）

## 官網來源
- 證交所上市融資融券明細 https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN ，以 date=YYYYMMDD、selectType=ALL、response=json 查詢。
- 櫃買中心融資餘額 https://www.tpex.org.tw/www/zh-tw/margin/balance ，以 date=民國年/MM/DD、type=EW、response=json 進行初步查詢。

目前只驗證兩個不同交易日2026/11/12及11/13的回傳資料是否真隨日期變化，表格是否含足夠股票列、欄位數是否一致、來源是否明示交易日期。若官方日期回傳格式異動、欄位變更、相同資料反覆返回，探測會停止並保留診斷。

## 不可直接套用
- TWSE 的融資融券明細和櫃買的融資交易單位可能以「交易單位（張）」計算，與每日行情成交股數、三大法人股數不能不經核實就直接相減或計算比例。
- 融資前日餘額與今日餘額公布／更帳時間不同；證交所官網明示應以前日餘額為準、今日餘額僅輔助參考。不應將後來更正的餘額誤當作先前交易時已知數據。
- 上櫃 OpenAPI 最新日並不代表可直接帶日期重建歷史。
- 檢驗結果永久標示 marginLotsVsSharesVerified=false、canMergeWithInstitutionalOrPriceFactors=false、top10=null、publishable=false。

GitHub Actions → Official Dated Margin Balance Source Probe 首次合併後可自動實測，僅輸出日期、欄名與資訊量指紋，不儲存私人部位與金鑰。驗證兩市場官方端點成功才進入下一階段研究資料歸檔。
