"""
讀取 data/holdings/ 底下至少 2 週的集保股權分散表快照，計算：
1. 大戶/千張/散戶持股比例週增 TOP50 排行（欄位風格參考市面上常見的「大戶籌碼分層週增」卡片）
2. 續買 / 回頭車 / 下車 / 續賣 分類（比較「上週增減」跟「本週增減」，需要至少 3 週資料）

執行方式：python analyze_holdings.py

注意：這裡不含「融資增減」「券資比」，那是融資融券資料，
需要另外接證交所的 MI_MARGN API 才能加進來，目前尚未實作。
"""

import pandas as pd
import glob
import os

HOLDINGS_DIR = "data/holdings"

# 持股分級代碼對照（TDCC 現行 15 級距，級距單位：股）
#   12~15 級 = 400,001 股以上，也就是一般說的「400張以上大戶」
#   15 級單獨抓出來 = 1,000,001 股以上，也就是「千張大戶」
#   1~11 級 = 400,000 股以下，也就是「散戶」（未達400張）
BIG_HOLDER_TIERS = {"12", "13", "14", "15"}
THOUSAND_LOT_TIERS = {"15"}
RETAIL_TIERS = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"}

# 判斷「買」「賣」的門檻，單位：百分點(pp)，可依需求調整
CHANGE_THRESHOLD = 1.0


def load_snapshot(path: str) -> pd.DataFrame:
    """
    讀一週的集保股權分散表，回傳每檔股票的：
    大戶持股比例(400張以上)、千張大戶持股比例(1000張以上)、散戶持股比例(未達400張)
    """
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    df["占集保庫存數比例%"] = pd.to_numeric(df["占集保庫存數比例%"], errors="coerce").fillna(0)
    df["持股分級"] = df["持股分級"].astype(str).str.strip()
    df["證券代號"] = df["證券代號"].astype(str).str.strip()

    # 拿掉公債類代碼（開頭是 Y）跟異常的調整欄位（分級代碼 16）
    df = df[~df["證券代號"].str.startswith("Y")]
    df = df[df["持股分級"] != "16"]

    def group_sum(tiers, name):
        return (
            df[df["持股分級"].isin(tiers)]
            .groupby("證券代號")["占集保庫存數比例%"]
            .sum()
            .rename(name)
        )

    big = group_sum(BIG_HOLDER_TIERS, "大戶比例")
    thousand = group_sum(THOUSAND_LOT_TIERS, "千張比例")
    retail = group_sum(RETAIL_TIERS, "散戶比例")

    result = pd.concat([big, thousand, retail], axis=1).fillna(0)
    return result


def list_snapshots():
    """回傳 (日期字串, 檔案路徑) 的清單，依日期由舊到新排序"""
    files = sorted(glob.glob(os.path.join(HOLDINGS_DIR, "*.csv")))
    return [(os.path.basename(f).replace(".csv", ""), f) for f in files]


def diff_two_weeks(df_new: pd.DataFrame, df_old: pd.DataFrame, suffix_new: str, suffix_old: str):
    """合併兩週資料，計算大戶/千張/散戶三個欄位各自的增減"""
    merged = df_new.join(df_old, how="outer", lsuffix=f"_{suffix_new}", rsuffix=f"_{suffix_old}").fillna(0)
    merged[f"大戶{suffix_new}增減"] = merged[f"大戶比例_{suffix_new}"] - merged[f"大戶比例_{suffix_old}"]
    merged[f"千張{suffix_new}增減"] = merged[f"千張比例_{suffix_new}"] - merged[f"千張比例_{suffix_old}"]
    merged[f"散戶{suffix_new}增減"] = merged[f"散戶比例_{suffix_new}"] - merged[f"散戶比例_{suffix_old}"]
    return merged


def main():
    snapshots = list_snapshots()

    if len(snapshots) == 0:
        print("data/holdings/ 底下還沒有任何資料，請先執行 fetch_holdings.py")
        return

    if len(snapshots) == 1:
        date0, path0 = snapshots[-1]
        df0 = load_snapshot(path0)
        print(f"目前只有一週資料（{date0}），還無法算週增，先列出這週大戶比例最高的 20 檔：")
        print(df0.sort_values("大戶比例", ascending=False).head(20))
        return

    # 至少有兩週：可以算「本週 vs 上週」的變化
    date0, path0 = snapshots[-1]   # 本週（最新）
    date1, path1 = snapshots[-2]   # 上週

    df0 = load_snapshot(path0)
    df1 = load_snapshot(path1)

    merged = diff_two_weeks(df0, df1, "本週", "上週")

    top50 = merged.sort_values("大戶本週增減", ascending=False).head(50)

    os.makedirs("reports", exist_ok=True)
    top50_path = f"reports/top50_{date0}.csv"
    top50.to_csv(top50_path, encoding="utf-8-sig")
    print(f"[週增TOP50] 已存檔：{top50_path}")
    print(top50[["大戶比例_本週", "大戶本週增減", "千張本週增減", "散戶本週增減"]].head(10))

    # 至少有三週：可以做續買/回頭車/下車/續賣分類
    if len(snapshots) < 3:
        print("\n只有兩週資料，還無法做續買/回頭車分類（需要至少三週資料）。")
        return

    date2, path2 = snapshots[-3]   # 上上週
    df2 = load_snapshot(path2)

    prev_merged = diff_two_weeks(df1, df2, "上週", "上上週")

    full = merged.join(prev_merged[["大戶上週增減"]], how="left").fillna(0)

    def classify(row):
        this_week = row["大戶本週增減"]
        last_week = row["大戶上週增減"]
        if last_week >= CHANGE_THRESHOLD and this_week >= CHANGE_THRESHOLD:
            return "續買"
        if last_week <= -CHANGE_THRESHOLD and this_week >= CHANGE_THRESHOLD:
            return "回頭車"
        if last_week >= CHANGE_THRESHOLD and this_week <= -CHANGE_THRESHOLD:
            return "下車"
        if last_week <= -CHANGE_THRESHOLD and this_week <= -CHANGE_THRESHOLD:
            return "續賣"
        return "無明顯變化"

    full["分類"] = full.apply(classify, axis=1)
    full = full.rename(columns={"大戶上週增減": "上週增減", "大戶本週增減": "本週增減"})

    turnover_path = f"reports/turnover_{date0}.csv"
    full[full["分類"] != "無明顯變化"].sort_values("本週增減", ascending=False).to_csv(
        turnover_path, encoding="utf-8-sig"
    )
    print(f"\n[續買/回頭車/下車/續賣] 已存檔：{turnover_path}")
    print(full["分類"].value_counts())


if __name__ == "__main__":
    main()
