# 台股 22 檔公開量化追蹤

使用 FinMind HTTP API 收集股價、成交量、法人及融資融券，以 TWSE／TPEx 官方資料核對，產生有交易日期與品質標記的日報及 GitHub Pages。公開流程不含私人持倉、成本、損益或自動下單。

唯一名單來源為 `config/watchlist_public.json`，目前固定 22 檔：3231、3481、3706、4585、6197、6213、6753、1815、2303、2317、2327、2382、2455、2478、2481、3090、00685L、00981A、1301、1312、2009、2301。名單數量或必要 ETF 不符會停止執行，不退回舊版 16 檔。

## 使用

1. 在 GitHub Actions Secrets 設定 `FINMIND_TOKEN`，Pages 來源選 GitHub Actions。
2. 手動執行 Daily Stock Report。開發分支只提供公開 artifact；main 才部署 Pages。
3. 排程臺灣週一至五 21:00，21:20、21:40 重查延遲資料；休市日產生明確標記的最近交易日報告。
4. 在 Actions Summary、public-daily-report artifact 或網站頁尾查看日報及品質報告。

GitHub 排程可能延遲。22 檔均會列出，但來源尚未發布或權限不足時顯示缺漏，不保證當天 21:00 所有欄位完整。八大官股需 Sponsor，目前顯示「無權限」。ETF 不套用公司基本面評分；全系統不使用虛構綜合分數。


## 全市場量化研發進度

[開啟公開量化研發進度頁面](https://leon5281ss.github.io/taylorstock-dashboard/quant-progress.html)：可查看正式／研究行情檔案日期數量、最近的已保存日期、121個觀測日期的初步門檻與尚未完成的資料品質關卡。數量由瀏覽器讀取公開 GitHub 檔案清單，若 API 暫時無法取得資料會明確顯示失敗；這個頁面不顯示私人部位、成本或任何金鑰。研究歷史尚未還原除權息，也缺乏歷史點時點公司母體與籌碼／基本面，**不提供 Top10、回測勝率或自動交易**。詳見 [開發任務 #6](https://github.com/leon5281ss/taylorstock-dashboard/issues/6)。

## 結構

- `scripts/market_pipeline/`：HTTP、正規化、官方核對、交易日、警報、官方政策公告、公開報告。
- `scripts/update_public_data.py`：公開入口；舊 `update_stock_data.py` 現為相同入口，舊 Excel／16 檔流程已退役。
- `scripts/market_pipeline/private_pnl.py`：獨立離線費稅計算，公開流程不呼叫。
- `tests/`：離線資料品質、日期、警報與隱私測試。
- `docs/data/`：網站公開資料；版本庫僅保留未收集的 null 初始化狀態。

新流程只需 Python 3.11+ 標準函式庫，不需額外安裝舊 Excel 相依套件。完整設定、警報門檻、單位、ETF 限制、私人損益費稅規則、測試與故障排查請見 [操作說明](docs/OPERATIONS.md)。

```text
python -m unittest discover -s tests -v
python scripts/validate_public.py
```

