# Taylorstock Dashboard

公開網址：<https://leon5281ss.github.io/taylorstock-dashboard/>

這是公開分享版股票追蹤儀表板，適合用 LINE 或瀏覽器分享給別人觀看。手機版會以卡片顯示，電腦版會以可搜尋、可篩選、可排序的表格顯示。

## 目前公開的資料

- 股票代號與名稱
- 投資分類
- 最新公開價格
- 技術面分數與總分
- 系統狀態：保留、觀察、減碼警訊、出場警訊、資料不足
- 主要警訊摘要
- 技術指標摘要
- 資料來源與更新日期

## 不會公開的資料

- API Key
- 券商帳號密碼
- 持有股數
- 成本均價
- 總資產金額
- 市值
- 未實現損益金額
- 本機絕對路徑，例如 C:\\Users\\Owner\\...

## 檔案結構

```text
docs/index.html              # GitHub Pages 首頁
docs/assets/style.css        # 手機與電腦響應式樣式
docs/assets/app.js           # 讀取 JSON 並渲染儀表板
docs/data/stocks.json        # 公開資料
scripts/update_public_data.py # 自動更新公開資料
config/watchlist_public.json # 公開追蹤股票清單
.github/workflows/deploy.yml # GitHub Pages 自動部署
```

## 新增或刪除股票

編輯 `config/watchlist_public.json`。

新增一檔時加入：

```json
{"code":"2330","name":"台積電","market":"TWSE","category":"半導體 / 晶圓代工"}
```

刪除股票時，移除對應那一行物件即可。儲存後可以手動執行 GitHub Actions，或等每天排程自動更新。

## 手動更新資料

到 GitHub repo 頁面：

1. 點上方 `Actions`
2. 選左側 `Deploy Stock Dashboard`
3. 點 `Run workflow`
4. 分支選 `main`
5. 再點一次 `Run workflow`

完成後，公開網址會更新為最新版。

## 自動更新

`.github/workflows/deploy.yml` 已設定：

- 每次推送到 `main` 會部署
- 可以手動 `Run workflow`
- 台灣時間約每週一到週五 16:30 自動更新一次

GitHub Actions 會執行：

```text
python scripts/update_public_data.py
```

然後把 `docs` 資料夾部署到 GitHub Pages。

## GitHub Pages 設定

如果第一次部署後網址還不能開，請到：

`Settings` → `Pages` → `Build and deployment` → `Source` 選 `GitHub Actions`

公開網址：

<https://leon5281ss.github.io/taylorstock-dashboard/>

## 投資與安全提醒

本系統僅供投資追蹤與風險提示，不構成買賣建議，不得自動下單，所有決策需人工確認。
