"""
掃描 data/ 和 reports/ 資料夾，產生一份清單 docs/manifest.json，
讓網頁儀表板 (docs/index.html) 知道目前有哪些日期/檔案可以讀取。

每次抓取資料後都應該執行這支程式，讓清單保持最新。
"""

import json
import glob
import os


def dates_from_dir(pattern: str):
    files = sorted(glob.glob(pattern))
    return [os.path.splitext(os.path.basename(f))[0] for f in files]


def main():
    manifest = {
        "institutional_dates": dates_from_dir("data/institutional/*.csv"),
        "price_dates": dates_from_dir("data/prices/*.csv"),
        "holdings_dates": dates_from_dir("data/holdings/*.csv"),
        "top50_reports": dates_from_dir("reports/top50_*.csv"),
        "turnover_reports": dates_from_dir("reports/turnover_*.csv"),
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("docs/manifest.json 已更新：")
    for key, values in manifest.items():
        print(f"  {key}: {len(values)} 筆")


if __name__ == "__main__":
    main()
