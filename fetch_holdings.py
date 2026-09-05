"""
抓取集保結算所「集保戶股權分散表」，全市場每檔股票、每個持股級距的人數/股數。
這份資料每週更新一次（通常週六更新，以週五收盤後的集保餘額為準）。

執行方式：python fetch_holdings.py
"""

import requests
import pandas as pd
from io import StringIO
import os

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

URL = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"


def fetch_holdings() -> pd.DataFrame:
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    return df


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    集保結算所偶爾會用「占」或「佔」，欄位名稱不完全固定，這裡統一處理成一致的欄名。
    """
    rename_map = {}
    for col in df.columns:
        clean = col.strip()
        if clean in ("佔集保庫存數比例%", "占集保庫存數比例%", "佔集保庫存數比例(%)", "占集保庫存數比例(%)"):
            rename_map[col] = "占集保庫存數比例%"
        elif clean in ("證券代號", "股票代號", "SecuritiesCode"):
            rename_map[col] = "證券代號"
        elif clean in ("持股分級", "SecuritiesHoldingRange"):
            rename_map[col] = "持股分級"
        elif clean in ("人數", "NumberofHolders"):
            rename_map[col] = "人數"
        elif clean in ("股數", "NumberofSharesUnits"):
            rename_map[col] = "股數"
    return df.rename(columns=rename_map)


def main():
    df = fetch_holdings()
    if df.empty:
        print("[集保股權分散表] 沒有資料，程式結束")
        return

    df = normalize_columns(df)

    # 第一欄通常是「資料日期」，格式 YYYYMMDD，整份資料共用同一天
    date_col = df.columns[0]
    raw_date = str(df[date_col].iloc[0]).strip()
    if len(raw_date) == 8 and raw_date.isdigit():
        date_dash = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    else:
        # 抓不到標準格式日期時，用今天日期當檔名備援
        from datetime import datetime
        from zoneinfo import ZoneInfo
        date_dash = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")

    os.makedirs("data/holdings", exist_ok=True)
    out_path = f"data/holdings/{date_dash}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[集保股權分散表] 已存檔：{out_path}（共 {len(df)} 列，涵蓋全市場個股 x 持股級距）")


if __name__ == "__main__":
    main()
