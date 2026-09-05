# 台股籌碼與價格自動追蹤

自動抓取三種資料：
1. **三大法人買賣超**（每個交易日）
2. **個股日成交資訊**（每個交易日，用來算均線）
3. **集保股權分散表**（每週一次，用來算大戶持股比例週增排行、續買/回頭車分類）

資料以 CSV 形式累積存放在 `data/` 資料夾中。

## 資料夾結構

```
twse-tracker/
├── fetch_data.py                              # 每日抓取：三大法人 + 個股成交
├── fetch_holdings.py                          # 每週抓取：集保股權分散表
├── analyze_holdings.py                        # 分析：週增TOP50 + 續買/回頭車分類
├── requirements.txt
├── .github/workflows/
│   ├── daily_fetch.yml                        # 每日排程
│   └── weekly_fetch_holdings.yml              # 每週排程（含自動分析）
├── data/
│   ├── institutional/2026-09-04.csv           # 三大法人，每天一個檔案
│   ├── prices/2026-09-04.csv                  # 個股成交，每天一個檔案
│   └── holdings/2026-09-04.csv                # 集保股權分散表，每週一個檔案
├── reports/
│   ├── top50_2026-09-04.csv                   # 大戶比例週增TOP50
│   └── turnover_2026-09-04.csv                # 續買/回頭車/下車/續賣分類
└── README.md
```

## 想免費回補近一個月歷史，不想乾等3週？

用 `backfill_holdings.py`：

1. 打開檔案，把 `WATCHLIST = ["2330", "2454", "2317"]` 改成你自己關注的股票代號
2. 執行 `python backfill_holdings.py`，它會用**集保結算所官網本身的免費查詢功能**（不是FinMind付費資料），
   把過去 5 個星期五的資料一次補回 `data/holdings/`
3. 跑完之後就有 5 週資料了，可以直接執行 `python analyze_holdings.py` 得到完整的週增排行跟續買/回頭車分類

**重要限制**：
- 這支程式只適合拿來查「你自己關注的一小把股票」，**不要**把 WATCHLIST 塞進全市場近 1800 檔股票，會很慢也容易被官網擋
- 因為只有你指定的股票有資料，`analyze_holdings.py` 跑出來的「TOP50排行」實際上只會涵蓋這幾檔，不是真正的全市場排名
- 如果之後想要「真正全市場」的歷史回補，才需要考慮付費訂閱 FinMind，或是接受讓 `fetch_holdings.py` 每週慢慢累積

## 關於週增TOP50跟續買/回頭車分類

- `fetch_holdings.py` 每週抓一次集保股權分散表的全市場快照
- `analyze_holdings.py` 讀取歷史快照，自動計算：
  - **累積到 2 週資料**：可以算出「本週大戶比例 - 上週大戶比例」，產出週增TOP50
  - **累積到 3 週資料**：才能做「續買/回頭車/下車/續賣」分類，因為要比較「上週的增減方向」跟「本週的增減方向」
- 換句話說，這個功能**第一次跑完全沒有東西**，要等 `weekly_fetch_holdings.yml` 連續跑 3 週之後，分類報表才會有意義
- 大戶／千張大戶的持股級距門檻是寫死在 `analyze_holdings.py` 的 `BIG_HOLDER_TIERS`／`THOUSAND_LOT_TIERS`，如果之後發現算出來的比例跟集保官網對不上，最可能是這裡的級距代碼需要微調

## 設定步驟（首次使用）

1. 到 GitHub 建立一個新的 repository（可以設為 Public 或 Private 都行）
2. 把這幾個檔案跟資料夾，依照上面的結構上傳到你的 repo：
   - `fetch_data.py`
   - `requirements.txt`
   - `.github/workflows/daily_fetch.yml`（注意 `.github` 是隱藏資料夾，要確定有上傳到）
3. 上傳完成後，到你的 repo 頁面 → 上方選單點 **Actions**
   - 如果看到「Workflows aren't being run on this forked repository」之類的提示，點選啟用 Actions
4. 確認排程是否正常運作：
   - 在 Actions 頁面左側選「每日抓取證交所資料」
   - 點右邊的 **Run workflow** 按鈕，手動觸發一次測試
   - 執行完成後（通常 1-2 分鐘），回到 repo 首頁看 `data/` 資料夾，應該會多出今天的 CSV 檔案

## 之後會發生什麼事

- 每個週一到週五台北時間下午 4 點，GitHub 會自動幫你執行 `fetch_data.py`
- 抓到的資料會自動存成 CSV 並且 commit 回你的 repo
- 遇到週末或國定假日，證交所沒有資料，程式會印出訊息但不會出錯
- 你完全不需要開電腦、不需要手動做任何事，資料會自動累積

## 之後要怎麼用這些資料

- 每個 CSV 都可以直接用 Excel 開，或用 pandas 讀取
- 累積個幾週資料後，就可以開始寫程式：
  - 讀取 `data/prices/` 底下所有檔案，算 MA5/MA10/MA20/MA60，篩選均線多頭排列的股票
  - 讀取 `data/institutional/` 底下所有檔案，算連續買超天數，找出籌碼集中的股票
- 這部分之後可以再請我幫你寫

## 常見問題

**Q: Actions 頁面顯示紅色叉叉，執行失敗怎麼辦？**
點進去看錯誤訊息，最常見的原因是 `.github/workflows/daily_fetch.yml` 沒有放對位置，
它必須在 repo 的最上層，路徑要是 `.github/workflows/daily_fetch.yml`，不能放在子資料夾裡。

**Q: 為什麼手動 Run workflow 之後，data 資料夾裡沒有新檔案？**
可能是執行的當下剛好抓不到資料（例如證交所該日資料還沒更新完），
或是當天不是交易日。點進去該次執行紀錄看 log 訊息確認原因。

**Q: 我想改成別的時間執行怎麼辦？**
修改 `.github/workflows/daily_fetch.yml` 裡的 `cron` 那一行，
時間是 UTC，台北時間要減 8 小時去換算。
