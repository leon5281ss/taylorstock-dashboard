# TDCC 第三方歷史週資料研究回補（非官方歷史驗證）

## 資料來源及信任邊界
官方最新週可由 TDCC dataset 1-5 取得並已保存在 data/tdcc_weekly_research。2026-11-13官方週資料與 wirelessr/tdcc-opendata-archive 最新週備份已實際核對：1961間公司完全一致，差異0。

同一外部備份也提供部分2026年4月後的週歷史，但**最新一週驗證通過，不代表此前每一週也由當時官方直接取得且未經修改**。

此模組下載歷史外部週資料、沿用已測試的17級與股數總合檢核，只放進 **data/tdcc_external_history_research**，嚴格與官方取得的 data/tdcc_weekly_research 分開。備份檔名與CSV內的日期必須完全相同；資料有異常、持股級距不完整、股數合計錯誤、來源回傳日期不符、公司數不足，都不會當作有效公司或驗證成功。

## 回補限制
- 以現有官方最新週日期作為鏡像交叉驗證的信任基準，每次首先重新比較同週外部CSV與本地直接取得的官方研究檔，必須全部共同公司一致才可研究舊檔。
- 先從GitHub備份列出2026年有效CSV檔名，從最新尚未保存的歷史週往前回補，每次最多4週、6次嘗試，至少2.5秒請求間距。
- 同一外部週不覆寫，已歸檔資料必須經版本、原始來源路徑SHA256、年月、公司數與安全標記檢查後才能跳過。
- 每一週都保存第三方公開歷史研究標記、來源網址及原始CSV SHA256。**沒有原始官方歷史發布時間佐證，不許寫成 official verified 或 daily data**。
- GitHub Actions → External TDCC Weekly Archive Research (Unverified History)，程式首次整合 main 時試跑，之後週日上午9:40進行非交易用途增量研究。

## 不可用於正式選股或績效
所有歷史外部週檔固定：status=external_third_party_mirror_unverified_historical、historicalOfficialDirectAcquisition=false、historicalPublicationTimeVerified=false、pointInTimeCompanyUniverse=false、historicalFactorReady=false、publishable=false、top10=null。

保留當時公司母體偏差、資料日期與真正發布日期、股權分級、除權息與減資、資料來源保存權利等後續待驗證事項。此模組不計算大戶進出買賣訊號，不自動填補日行情、不發送Telegram推薦、不進行回測或自動交易。每週的公開歷史備份不能自動取得與官方快照同等可信度。
