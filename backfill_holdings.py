"""
免費回補「近一個月」集保股權分散表歷史，只限你自己指定的觀察名單股票（不是全市場）。

資料來源：集保結算所官網本身的查詢功能（完全免費，不需要 FinMind 付費會員）
網址：https://www.tdcc.com.tw/smWeb/QryStockAjax.do

限制：
- 這是集保官網本身提供的免費查詢功能，本來就只保留近 52 週（約一年）資料
- 一次請求只能查「一檔股票、一個星期五」，所以本程式會迴圈：
  每檔股票 x 每個星期五，各發一次請求
- 只建議用在你自己關注的一小把股票（幾檔到幾十檔）。
  不要拿來抓全市場，一來近 1800 檔太耗時，二來容易被官網判定異常流量而擋掉
- 這是「一次性回補」用的程式，不用排程，手動跑一次把過去幾週補齊即可，
  之後就交給 fetch_holdings.py 每週自動累積

執行前請先修改下面的 WATCHLIST，填入你想回補的股票代號。
執行方式：python backfill_holdings.py
"""

import requests
import pandas as pd
from io import StringIO
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock",
}

URL = "https://www.tdcc.com.tw/smWeb/QryStockAjax.do"

# ↓↓↓ 請填入你想回補的股票代號 ↓↓↓
WATCHLIST = ["2330", "2454", "2317"]

# 想回補幾個星期五（近一個月大約 4-5 週）
WEEKS_BACK = 5

# 每次請求之間的間隔秒數，放慢速度、避免對官網造成負擔或被擋
REQUEST_DELAY_SECONDS = 1.5


def recent_fridays(n: int):
    """回傳最近 n 個星期五的日期字串（YYYYMMDD），由新到舊排序"""
    today = datetime.now(ZoneInfo("Asia/Taipei")).date()
    offset = (today.weekday() - 4) % 7  # weekday(): 星期一=0 ... 星期五=4
    last_friday = today - timedelta(days=offset)
    return [(last_friday - timedelta(weeks=i)).strftime("%Y%m%d") for i in range(n)]


def fetch_one(stock_id: str, sca_date: str):
    """查詢單一股票、單一週的股權分散表，回傳 DataFrame，查不到回傳 None"""
    payload = {
        "scaDates": sca_date,
        "scaDate": sca_date,
        "SqlMethod": "StockNo",
        "StockNo": stock_id,
        "radioStockNo": stock_id,
        "StockName": "",
        "REQ_OPR": "SELECT",
        "clkStockNo": stock_id,
        "clkStockName": "",
    }
    resp = requests.post(URL, data=payload, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    try:
        tables = pd.read_html(StringIO(resp.text))
    except ValueError:
        print(f"  [{stock_id} {sca_date}] 沒解析到任何表格（該週可能無資料，或頁面格式已變動）")
        return None

    # 找出欄位長得像股權分散表的那一張（通常欄位含「持股分級」或「級距」）
    target = None
    for t in tables:
        cols = [str(c) for c in t.columns]
        if any("持股分級" in c or "級距" in c for c in cols):
            target = t
            break

    if target is None or target.empty:
        print(f"  [{stock_id} {sca_date}] 找不到股權分散表格")
        return None

    target = target.rename(columns=lambda c: str(c).strip())
    rename_map = {}
    for c in target.columns:
        if "持股分級" in c or "級距" in c:
            rename_map[c] = "持股分級"
        elif c == "人數":
            rename_map[c] = "人數"
        elif "股數" in c and "占" not in c and "比例" not in c:
            rename_map[c] = "股數"
        elif "比例" in c:
            rename_map[c] = "占集保庫存數比例%"
    target = target.rename(columns=rename_map)

    keep_cols = [c for c in ["持股分級", "人數", "股數", "占集保庫存數比例%"] if c in target.columns]
    if not keep_cols:
        print(f"  [{stock_id} {sca_date}] 表格欄位跟預期不符，先印出原始欄位供你比對：{list(target.columns)}")
        return None

    target = target[keep_cols].copy()
    target["證券代號"] = stock_id
    target["資料日期"] = sca_date
    return target


def main():
    os.makedirs("data/holdings", exist_ok=True)
    fridays = recent_fridays(WEEKS_BACK)
    print(f"準備回補股票：{WATCHLIST}")
    print(f"準備回補週別：{fridays}\n")

    by_date = {}

    for stock_id in WATCHLIST:
        for sca_date in fridays:
            df = fetch_one(stock_id, sca_date)
            if df is not None:
                by_date.setdefault(sca_date, []).append(df)
                print(f"  [{stock_id} {sca_date}] OK，共 {len(df)} 列")
            time.sleep(REQUEST_DELAY_SECONDS)

    if not by_date:
        print("\n沒有成功抓到任何資料。建議先手動測試單一股票單一週，確認網站回傳格式是否跟程式預期的一致。")
        return

    for sca_date, dfs in by_date.items():
        date_dash = f"{sca_date[:4]}-{sca_date[4:6]}-{sca_date[6:]}"
        out_path = f"data/holdings/{date_dash}.csv"
        combined = pd.concat(dfs, ignore_index=True)

        if os.path.exists(out_path):
            existing = pd.read_csv(out_path, dtype=str)
            combined = pd.concat([existing, combined], ignore_index=True).drop_duplicates(
                subset=["證券代號", "持股分級"], keep="last"
            )

        combined.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"\n已存檔：{out_path}（{len(combined)} 列）")


if __name__ == "__main__":
    main()
