"""
每日抓取台灣證交所資料：
1. 三大法人買賣超日報 (T86)
2. 個股日成交資訊 (STOCK_DAY_ALL)

執行方式：python fetch_data.py
會自動抓「今天」的資料，存成 CSV，檔名依日期命名，方便之後累積歷史、算均線跟籌碼分數。
"""

import requests
import pandas as pd
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import sys

# ---------- 共用設定 ----------

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def today_str_yyyymmdd() -> str:
    """回傳台北時區的今天日期，格式 YYYYMMDD"""
    return datetime.now(TAIPEI_TZ).strftime("%Y%m%d")


def today_str_dash() -> str:
    """回傳台北時區的今天日期，格式 YYYY-MM-DD，用來當檔名"""
    return datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")


def roc_date_to_dash(v) -> str | None:
    """
    把民國格式日期字串（例如 '1150904'）轉成西元 'YYYY-MM-DD'。
    如果格式看起來已經是西元日期（8碼），也一併處理。
    轉不出來就回傳 None。
    """
    v = str(v).strip()
    if len(v) == 7 and v.isdigit():
        roc_year = int(v[:3])
        month = v[3:5]
        day = v[5:7]
        return f"{roc_year + 1911}-{month}-{day}"
    if len(v) == 8 and v.isdigit():
        return f"{v[:4]}-{v[4:6]}-{v[6:8]}"
    return None
    """把 '1,234' 這種帶逗號的字串轉成整數，轉不了就回傳 0"""
    if value is None:
        return 0
    value = str(value).replace(",", "").strip()
    if value in ("", "--", "N/A"):
        return 0
    try:
        return int(value)
    except ValueError:
        try:
            return int(float(value))
        except ValueError:
            return 0


# ---------- 抓取三大法人買賣超 (T86) ----------

def fetch_institutional_flow(date_str: str) -> pd.DataFrame | None:
    """
    抓取指定日期的三大法人買賣超日報 (T86)。
    date_str 格式：YYYYMMDD
    若當天不是交易日（週末、國定假日），會回傳 None。
    """
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    params = {"date": date_str, "selectType": "ALL", "response": "json"}

    resp = requests.get(url, params=params, headers=HEADERS, timeout=15)

    if resp.status_code != 200:
        print(f"[三大法人] HTTP狀態碼異常：{resp.status_code}")
        print(f"回應內容前200字：{resp.text[:200]}")
        return None

    try:
        payload = resp.json()
    except requests.exceptions.JSONDecodeError:
        print("[三大法人] 回應不是有效的JSON，可能被證交所擋掉了（常見於雲端伺服器IP）")
        print(f"HTTP狀態碼：{resp.status_code}")
        print(f"回應內容前200字：{resp.text[:200]!r}")
        return None

    if payload.get("stat") != "OK" or not payload.get("data"):
        print(f"[三大法人] {date_str} 沒有資料（可能是非交易日）")
        return None

    df = pd.DataFrame(payload["data"], columns=payload["fields"])

    # 把逗號數字欄位轉成整數，方便之後計算
    numeric_cols = [c for c in df.columns if c not in ("證券代號", "證券名稱")]
    for col in numeric_cols:
        df[col] = df[col].apply(to_int)

    # 外資買賣超合計 = 外陸資(不含外資自營商) + 外資自營商
    df["外資買賣超合計"] = (
        df["外陸資買賣超股數(不含外資自營商)"] + df["外資自營商買賣超股數"]
    )

    df["資料日期"] = date_str
    return df


# ---------- 三大法人買賣超 (T86)：找不到今天的資料就往前找 ----------

def fetch_institutional_flow_latest(max_lookback_days: int = 7):
    """
    從今天開始往前找，直到找到有資料的交易日為止，最多往前找 max_lookback_days 天。
    回傳 (DataFrame, 日期字串YYYY-MM-DD)，找不到就回傳 (None, None)。
    """
    base = datetime.now(TAIPEI_TZ)
    for i in range(max_lookback_days):
        d = base - timedelta(days=i)
        date_compact = d.strftime("%Y%m%d")
        df = fetch_institutional_flow(date_compact)
        if df is not None:
            return df, d.strftime("%Y-%m-%d")
    return None, None


# ---------- 抓取個股日成交資訊 (STOCK_DAY_ALL) ----------

def fetch_daily_price() -> pd.DataFrame | None:
    """
    抓取全部上市股票「當日」成交資訊。
    這支 API 沒有 date 參數，永遠回傳最近一個交易日的資料。

    注意：證交所這支 API 有時候即使指定 response=json，
    仍會回傳 CSV 格式的文字內容（欄位是中文），這裡做雙重解析、互相備援。
    """
    url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL"
    params = {"response": "json"}

    resp = requests.get(url, params=params, headers=HEADERS, timeout=15)

    if resp.status_code != 200:
        print(f"[個股日成交] HTTP狀態碼異常：{resp.status_code}")
        print(f"回應內容前200字：{resp.text[:200]}")
        return None

    df = None

    try:
        payload = resp.json()
        if payload.get("data"):
            df = pd.DataFrame(payload["data"], columns=payload["fields"])
        else:
            print("[個股日成交] JSON格式正常，但沒有資料（可能是非交易日）")
            return None
    except requests.exceptions.JSONDecodeError:
        # 退而求其次：證交所這次回傳的其實是CSV格式文字，改用CSV方式解析
        print("[個股日成交] 回應不是JSON格式，改嘗試用CSV格式解析...")
        try:
            df = pd.read_csv(io.StringIO(resp.text))
        except Exception as e:
            print(f"[個股日成交] CSV解析也失敗：{e}")
            print(f"回應內容前200字：{resp.text[:200]!r}")
            return None

        df.columns = [str(c).strip() for c in df.columns]
        rename_map = {
            "日期": "Date", "證券代號": "Code", "證券名稱": "Name",
            "成交股數": "TradeVolume", "成交金額": "TradeValue",
            "開盤價": "OpeningPrice", "最高價": "HighestPrice", "最低價": "LowestPrice",
            "收盤價": "ClosingPrice", "漲跌價差": "Change", "成交筆數": "Transaction",
        }
        df = df.rename(columns=rename_map)

    if df is None or df.empty:
        print("[個股日成交] 沒有資料")
        return None

    numeric_cols = [
        "TradeVolume", "TradeValue", "OpeningPrice",
        "HighestPrice", "LowestPrice", "ClosingPrice", "Transaction",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].apply(to_int)

    return df


# ---------- 主程式 ----------

def main():
    os.makedirs("data/institutional", exist_ok=True)
    os.makedirs("data/prices", exist_ok=True)

    fetched_something = False

    # 三大法人買賣超（自動往前找最近有資料的交易日）
    inst_df, inst_date_dash = fetch_institutional_flow_latest()
    if inst_df is not None:
        out_path = f"data/institutional/{inst_date_dash}.csv"
        inst_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"[三大法人] 已存檔：{out_path}（{len(inst_df)} 檔股票，資料日期 {inst_date_dash}）")
        fetched_something = True
    else:
        print("[三大法人] 往前找了好幾天都沒有資料，可能是連續假期或被擋掉了")

    # 個股日成交資訊（用資料本身的日期命名，不是用程式執行當天）
    price_df = fetch_daily_price()
    if price_df is not None:
        actual_date_dash = None
        if "Date" in price_df.columns and len(price_df) > 0:
            actual_date_dash = roc_date_to_dash(price_df["Date"].iloc[0])
        if actual_date_dash is None:
            actual_date_dash = today_str_dash()
            print(f"[個股日成交] 無法從資料判斷實際交易日，改用程式執行日期 {actual_date_dash} 命名")

        out_path = f"data/prices/{actual_date_dash}.csv"
        price_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"[個股日成交] 已存檔：{out_path}（{len(price_df)} 檔股票，資料日期 {actual_date_dash}）")
        fetched_something = True

    if not fetched_something:
        print("這次兩種資料都抓不到，程式正常結束。")
        sys.exit(0)


if __name__ == "__main__":
    main()
