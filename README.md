# API 自動更新 Excel 股票追蹤系統 v2

這是 Windows 本機可執行的第二階段工具：讀取 `input/watchlist.xlsx` 的「01_手動填寫持股」，只更新 API/報表欄位，不覆蓋原始 Excel。

第二階段新增：

- 月營收追蹤與基本面警訊
- 三大法人籌碼追蹤
- 財報與估值追蹤
- 新聞與產業風險欄位
- 100 分綜合評分模型

輸出檔會另存到 `reports/output_report_stage2_YYYY-MM-DD.xlsx`，每日中文摘要會輸出到 `reports/daily_report_stage2_YYYY-MM-DD.md`。

## 1. 如何安裝 Python

到 Python 官方網站下載 Windows 版 Python 3.11 或更新版本，安裝時勾選 `Add python.exe to PATH`。

安裝後開啟 PowerShell，確認：

```powershell
python --version
pip --version
```

## 2. 如何安裝套件

在本專案資料夾執行：

```powershell
pip install -r requirements.txt
```

## 3. 如何放入 Excel 檔案

把你的手動持股 Excel 放到：

```text
input/watchlist.xlsx
```

目前已先放入你提供的 `Codex_API自動更新股票追蹤_16家公司版.xlsx` 複本。請只在「01_手動填寫持股」維護黃色/手動欄位，例如是否追蹤、股票代號、持有股數、成本均價、投資目的與備註。

## 4. 如何執行

```powershell
python scripts/update_stock_data.py
```

若只想測試 Excel 回寫、報告與 log 流程，不打 API：

```powershell
python scripts/update_stock_data.py --dry-run
```

## 5. 如何查看 reports 資料夾

每天執行後會產生：

```text
reports/output_report_stage2_YYYY-MM-DD.xlsx
reports/daily_report_stage2_YYYY-MM-DD.md
logs/update_log_YYYY-MM-DD.txt
```

`output_report_stage2` 是保留原始輸入並新增/更新以下工作表的每日 Excel：

```text
04_自動更新結果
09_資料來源
11_月營收追蹤
12_法人籌碼追蹤
13_財報估值追蹤
14_新聞風險追蹤
15_第二階段綜合評分
```

## 5-1. 如何查看手機/電腦版網頁儀表板

第二階段也會產生一個可直接打開的響應式網頁：

```text
docs/index.html
```

你可以用檔案總管打開：

```text
C:\Users\Owner\Documents\Codex\2026-06-07\1-2-3-4-5-6\docs\index.html
```

網頁資料來自：

```text
docs/data/stocks.json
docs/data/stocks-data.js
```

每次執行：

```powershell
python scripts\update_stock_data.py
```

或：

```powershell
& "C:\Users\Owner\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\update_stock_data.py
```

系統會同步更新 Excel、Markdown 報告與網頁資料。

如果只想從已經產出的 Excel 重新產生網頁資料，不重新抓 API，可以執行：

```powershell
& "C:\Users\Owner\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\update_stock_data.py --export-dashboard-from "reports\output_report_stage2_2026-06-11.xlsx"
```

桌機版會顯示可搜尋、可篩選、可依總分排序的核心表格；手機寬度小於 640px 時會自動切換成卡片列表，不會把 40 欄表格塞進手機畫面。

## 5-2. 如何部署成可以傳給別人的網址

建議使用 GitHub Pages。部署後網址會長得像：

```text
https://你的GitHub帳號.github.io/你的專案名稱/
```

別人用手機、電腦、LINE 點開都可以看，不需要下載 Excel。

### 第一次部署步驟

1. 在 GitHub 建立一個 repository，例如：

```text
stock-dashboard
```

2. 建議 repository 設成 Private，因為專案裡有更新腳本與可能的投資資料。GitHub Pages 對外發布的只有 `docs` 網頁。

3. 把本專案推到 GitHub。

4. 到 GitHub repository 的：

```text
Settings → Pages
```

把 Source 設為：

```text
GitHub Actions
```

5. 到：

```text
Actions → Deploy Stock Dashboard → Run workflow
```

手動執行一次。

6. 成功後，到：

```text
Settings → Pages
```

就會看到公開網址。

### 私有 Excel 不要放到公開網頁

公開網頁只使用：

```text
docs/data/stocks.json
```

這個 JSON 預設不公開：

```text
持有股數
成本均價
市值
未實現損益金額
本機 C:\ 路徑
API Key
券商帳密
```

公開網頁會顯示：

```text
股票代號
股票名稱
投資分類
最新價格
未實現損益率
技術/基本/籌碼/新聞分數
總分
狀態
主要警訊
是否需要人工確認
更新日期
```

### GitHub Actions 自動更新

公開部署版預設不使用你的私有 Excel，而是讀取：

```text
config/watchlist_public.json
```

這個檔案只包含股票代號、名稱、分類，不含持股數、成本、總資產或未實現損益金額。

`.github/workflows/deploy.yml` 會每天台灣時間約 16:30 自動：

```text
讀取 config/watchlist_public.json
→ 執行 scripts/update_public_data.py
→ 產生 docs/data/stocks.json
→ 部署 GitHub Pages
```

如果未來你真的要讓 GitHub Actions 讀私有 Excel，請用 GitHub Secrets，不要直接把 `input/watchlist.xlsx` 放進公開 repo。

### GitHub Secrets

如果你要讓 GitHub Actions 取得私有持倉與公開資料來源的完整自動更新，請在 GitHub repo 的 `Settings → Secrets and variables → Actions` 新增：

- `POSITIONS_PRIVATE_JSON_B64`
- `FINMIND_TOKEN`，如果你的 FinMind 帳號或方案需要 token

目前公開資料來源設定在 `config/data_sources_public.json`，其中 `price`、`technical`、`revenue`、`chip`、`financial`、`news` 都是公開市場資料，不包含私人持倉成本或股數。

## 5-3. 如何確認自動更新成功

到 GitHub：

```text
Actions → Deploy Stock Dashboard
```

如果最新一筆是綠色勾勾，代表更新與部署成功。

如果失敗，點進去看錯誤訊息。常見原因：

- 沒有設定 `WATCHLIST_XLSX_BASE64`
- FinMind 或公開 API 暫時無法連線
- Excel 欄位被改名
- 股票代號或市場填錯

## 5-4. 新增、刪除、修改股票

你主要只改這個檔案：

```text
input/watchlist.xlsx
```

在「01_手動填寫持股」：

- 新增股票：新增一列，`是否追蹤(Y/N)` 填 `Y`
- 刪除股票：刪掉該列，或把 `是否追蹤(Y/N)` 改成 `N`
- 修改成本價：改 `成本均價`
- 修改持股數：改 `持有股數`

如果是公開網頁要新增或刪除股票，請改：

```text
config/watchlist_public.json
```

如果是你本機完整 Excel 系統要新增、刪除或修改成本，仍然改：

```text
input/watchlist.xlsx
```

## 6. 如何設定 Windows 工作排程器每天 16:00 自動執行

1. 開啟「工作排程器」。
2. 選「建立基本工作」。
3. 名稱填：`股票追蹤每日更新`。
4. 觸發程序選「每天」，時間設 `16:00`。
5. 動作選「啟動程式」。
6. 程式填你的 Python 路徑，例如：

```text
C:\Users\Owner\AppData\Local\Programs\Python\Python311\python.exe
```

7. 引數填：

```text
scripts\update_stock_data.py
```

8. 起始位置填本專案資料夾路徑。

## 7. API 抓不到資料時如何排查

先看當天 log：

```text
logs/update_log_YYYY-MM-DD.txt
```

常見原因：

- 網路中斷或 API 暫時無回應。
- FinMind 免費 API 暫時限流。
- 股票代號錯誤或市場類別錯誤。
- 今日尚未有收盤資料。
- 歷史資料不足，無法計算 MA120 或 MA240。

若 API 失敗，程式會保留原輸入資料，該檔股票狀態標示「資料不足」，並在報告與 log 中列出原因。

## 8. 如何新增股票

到 `input/watchlist.xlsx` 的「01_手動填寫持股」新增一列：

- 是否追蹤填 `Y`
- 市場填 `TWSE` 或 `TPEx`
- 股票代號填 4 碼
- 股票名稱、投資分類、持有股數、成本均價依實際情況填寫

下一次執行會自動讀取，不需要修改程式。

## 9. 如何停用某檔股票追蹤

把「是否追蹤(Y/N)」改成 `N`。程式會保留該列，不進行 API 更新。

## 安全限制

- 不登入元大帳戶。
- 不自動下單。
- 不保存券商帳號密碼、OTP、憑證或交易密碼。
- 減碼警訊與出場警訊只做風控提醒，必須人工確認。

## 第二階段評分規則

綜合評分共 100 分：

```text
技術面：30 分
基本面：30 分
籌碼面：20 分
新聞與產業：20 分
```

狀態判斷：

```text
80 分以上：保留
65-79 分：保留但觀察
50-64 分：觀察
40-49 分：減碼警訊
40 分以下：出場警訊
```

所有「減碼警訊」與「出場警訊」都會標示：

```text
需要人工確認
不可自動下單
不可直接執行交易
```

## 第三版擴充方向

後續可加強新聞摘要品質、法說會逐字稿、公司展望判讀、三大法人分點細節、產業趨勢自動摘要與通知。
