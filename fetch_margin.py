"""
抓取台灣證交所「個股融資融券餘額」日報表 (MI_MARGN)，
用來算融資增減、券資比。

執行方式：python fetch_margin.py
資料來源：https://www.twse.com.tw/exchangeReport/MI_MARGN
"""

import requests
import pandas as pd
import io
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def today_str_yyyymmdd() -> str:
    return datetime.now(TAIPEI_TZ).strftime("%Y%m%d")


def today_str_dash() -> str:
    return datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d")


def clean_code(v: str) -> str:
    """把 ="0050" 這種Excel escape格式，還原成單純的 0050"""
    v = str(v).strip()
    if v.startswith("="):
        v = v[1:]
    return v.strip('"').strip()


def to_int(v) -> int:
    if v is None:
        return 0
    v = str(v).replace(",", "").replace('"', "").strip()
    if v in ("", "--", "X", "O"):
        return 0
    try:
        return int(v)
    except ValueError:
        try:
            return int(float(v))
        except ValueError:
            return 0


def fetch_margin(date_str: str) -> pd.DataFrame | None:
    """
    抓取指定日期的個股融資融券餘額表。
    date_str 格式：YYYYMMDD
    """
    url = "https://www.twse.com.tw/exchangeReport/MI_MARGN"
    params = {"response": "csv", "date": date_str, "selectType": "ALL"}

    resp = requests.get(url, params=params, headers=HEADERS, timeout=20)

    if resp.status_code != 200:
        print(f"[融資融券] HTTP狀態碼異常：{resp.status_code}")
        return None

    resp.encoding = "cp950"  # 證交所CSV是Big5編碼，不轉的話中文會亂碼
    text = resp.text

    if not text or len(text) < 50:
        print("[融資融券] 回應內容太短，可能被擋掉了，或非交易日")
        print(f"回應內容前200字：{text[:200]!r}")
        return None

    lines = text.splitlines()

    # 個股資料表格的表頭那一行，開頭是「代號」；前面幾行是全市場信用交易統計，先跳過
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith('"代號"'):
            header_idx = i
            break

    if header_idx is None:
        print("[融資融券] 找不到個股資料表頭，可能是非交易日或證交所格式已變動")
        print("回應內容前300字：")
        print(text[:300])
        return None

    # 從表頭開始收集資料列，遇到空行或「備註」開頭的行就停止
    data_lines = [lines[header_idx]]
    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if stripped == "" or stripped.startswith('"備註'):
            break
        data_lines.append(line)

    clean_text = "\n".join(data_lines)

    try:
        df = pd.read_csv(io.StringIO(clean_text))
    except Exception as e:
        print(f"[融資融券] CSV解析失敗：{e}")
        print("前300字內容：")
        print(clean_text[:300])
        return None

    df.columns = [str(c).strip().strip('"') for c in df.columns]

    if "代號" not in df.columns:
        print(f"[融資融券] 欄位跟預期不符，實際欄位：{list(df.columns)}")
        return None

    df["證券代號"] = df["代號"].apply(clean_code)
    df["證券名稱"] = df["名稱"].astype(str).str.strip()

    # 這份報表「融資」「融券」是合併儲存格當大標題，蓋在下面一排小標題(買進/賣出/今日餘額...)之上，
    # pandas讀進來後只留得下小標題，融資/融券字樣會遺失，欄位變成重複名稱(今日餘額, 今日餘額.1)。
    # 所以關鍵字比對抓不到，改用固定欄位順序備援：
    # 代號,名稱, 買進,賣出,現金償還,前日餘額,今日餘額,次一營業日限額(這6欄是融資),
    #            買進.1,賣出.1,現券償還,前日餘額.1,今日餘額.1,次一營業日限額.1(這6欄是融券), 資券互抵,註記
    def find_col(keyword_list):
        for col in df.columns:
            if all(k in col for k in keyword_list):
                return col
        return None

    margin_today_col = find_col(["融資", "今日餘額"])
    margin_yesterday_col = find_col(["融資", "前日餘額"])
    short_today_col = find_col(["融券", "今日餘額"])
    short_yesterday_col = find_col(["融券", "前日餘額"])

    if not all([margin_today_col, margin_yesterday_col, short_today_col, short_yesterday_col]):
        cols = list(df.columns)
        if len(cols) >= 13:
            margin_yesterday_col = margin_yesterday_col or cols[5]
            margin_today_col = margin_today_col or cols[6]
            short_yesterday_col = short_yesterday_col or cols[11]
            short_today_col = short_today_col or cols[12]
            print("[融資融券] 欄位名稱沒有融資/融券字樣，改用固定欄位順序對應")

    if not all([margin_today_col, margin_yesterday_col, short_today_col, short_yesterday_col]):
        print(f"[融資融券] 找不到餘額欄位，實際欄位：{list(df.columns)}")
        return None

    df["融資今日餘額"] = df[margin_today_col].apply(to_int)
    df["融資前日餘額"] = df[margin_yesterday_col].apply(to_int)
    df["融券今日餘額"] = df[short_today_col].apply(to_int)
    df["融券前日餘額"] = df[short_yesterday_col].apply(to_int)

    df["融資增減"] = df["融資今日餘額"] - df["融資前日餘額"]
    df["融券增減"] = df["融券今日餘額"] - df["融券前日餘額"]
    df["券資比"] = df.apply(
        lambda r: round(r["融券今日餘額"] / r["融資今日餘額"] * 100, 2) if r["融資今日餘額"] > 0 else 0,
        axis=1,
    )

    result = df[[
        "證券代號", "證券名稱",
        "融資今日餘額", "融資前日餘額", "融資增減",
        "融券今日餘額", "融券前日餘額", "融券增減",
        "券資比",
    ]].copy()

    return result


def fetch_margin_latest(max_lookback_days: int = 7):
    """從今天開始往前找，直到找到有資料的交易日為止"""
    base = datetime.now(TAIPEI_TZ)
    for i in range(max_lookback_days):
        d = base - timedelta(days=i)
        date_compact = d.strftime("%Y%m%d")
        df = fetch_margin(date_compact)
        if df is not None:
            return df, d.strftime("%Y-%m-%d")
    return None, None


def main():
    df, date_dash = fetch_margin_latest()
    if df is None:
        print("往前找了好幾天都抓不到融資融券資料，程式正常結束。")
        return

    os.makedirs("data/margin", exist_ok=True)
    out_path = f"data/margin/{date_dash}.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"[融資融券] 已存檔：{out_path}（{len(df)} 檔股票，資料日期 {date_dash}）")


if __name__ == "__main__":
    main()
