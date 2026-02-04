import pandas as pd

# =========================================================
# Merge exam rooms (greedy bin packing) with constraints:
# - Group by KEY
# - Only merge if different COURSE ID
# - Capacity constraint uses EXAM CAPACITY (fallback to CAPACITY if missing)
# - Output:
#   1) merge_suggestions.csv (detailed merged rooms)
#   2) savings_by_key.csv (stats per KEY)
#   3) savings_by_date.csv (stats per DATE)
#   4) tongket.csv (overall summary)
# =========================================================

INPUT_FILE = "phong_thi.csv"

# If True: do NOT fallback EXAM CAPACITY -> CAPACITY (stricter)
STRICT_EXAMCAP_ONLY = False

# If True: validate that within each KEY, DATE/TIME/CAMPUS are consistent
STRICT_KEY_CONSISTENCY_CHECK = False


def parse_date_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Robust DATE parsing:
    1) Try Excel serial numbers (only on numeric values)
    2) Fallback to dd/mm/yyyy strings
    """
    date_numeric = pd.to_numeric(df["DATE"], errors="coerce")

    df["DATE_DT"] = pd.to_datetime(
        date_numeric,
        unit="D",
        origin="1899-12-30",
        errors="coerce"
    )

    mask_na = df["DATE_DT"].isna()
    df.loc[mask_na, "DATE_DT"] = pd.to_datetime(
        df.loc[mask_na, "DATE"],
        dayfirst=True,
        errors="coerce"
    )

    df["DATE_ONLY"] = df["DATE_DT"].dt.date
    return df


def clean_numeric(df: pd.DataFrame) -> pd.DataFrame:
    df["STUDENTS"] = pd.to_numeric(df["STUDENTS"], errors="coerce").fillna(0).astype(int)
    df["CAPACITY"] = pd.to_numeric(df["CAPACITY"], errors="coerce")
    df["EXAM CAPACITY"] = pd.to_numeric(df["EXAM CAPACITY"], errors="coerce")
    return df


def check_required_columns(df: pd.DataFrame) -> None:
    required = ["COURSE ID", "ROOM ID", "DATE", "TIME", "CAMPUS", "STUDENTS", "CAPACITY", "KEY", "EXAM CAPACITY"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def merge_rooms(df: pd.DataFrame):
    merged_results = []
    summary_key = []

    for key_val, group in df.groupby("KEY", dropna=False):
        rooms_before = len(group)

        if STRICT_KEY_CONSISTENCY_CHECK:
            uniq_date = group["DATE_ONLY"].nunique(dropna=True)
            uniq_time = group["TIME"].nunique(dropna=True)
            uniq_campus = group["CAMPUS"].nunique(dropna=True)
            if uniq_date > 1 or uniq_time > 1 or uniq_campus > 1:
                print(
                    f"KEY '{key_val}' mixes sessions: "
                    f"dates={uniq_date}, times={uniq_time}, campus={uniq_campus}"
                )

        group_sorted = group.sort_values("STUDENTS", ascending=False)

        bins = []

        for _, row in group_sorted.iterrows():
            placed = False
            course_id = row["COURSE ID"]
            n_sv = int(row["STUDENTS"])

            exam_cap = row["EXAM CAPACITY"]
            if pd.isna(exam_cap):
                if STRICT_EXAMCAP_ONLY:
                    exam_cap = 0
                else:
                    exam_cap = row["CAPACITY"]

            for b in bins:
                ok_distinct = course_id not in b["courses"]
                ok_capacity = (b["current"] + n_sv) <= b["exam_capacity"]
                if ok_distinct and ok_capacity:
                    b["items"].append(row)
                    b["courses"].add(course_id)
                    b["current"] += n_sv
                    placed = True
                    break

            if not placed:
                bins.append(
                    {
                        "target_room": row["ROOM ID"],
                        "exam_capacity": exam_cap,
                        "current": n_sv,
                        "courses": {course_id},
                        "items": [row],
                    }
                )

        date_only = group_sorted.iloc[0]["DATE_ONLY"]
        time_val = group_sorted.iloc[0]["TIME"]
        campus_val = group_sorted.iloc[0]["CAMPUS"]

        for b in bins:
            merged_results.append(
                {
                    "KEY": key_val,
                    "DATE": date_only,
                    "TIME": time_val,
                    "CAMPUS": campus_val,
                    "TARGET ROOM": b["target_room"],
                    "EXAM CAPACITY": b["exam_capacity"],
                    "TOTAL STUDENTS": b["current"],
                    "COURSES MERGED": ", ".join(
                        [f'{r["COURSE ID"]}({int(r["STUDENTS"])})' for r in b["items"]]
                    ),
                }
            )

        rooms_after = len(bins)
        summary_key.append(
            {
                "DATE": date_only,
                "KEY": key_val,
                "ROOMS_BEFORE": rooms_before,
                "ROOMS_AFTER": rooms_after,
                "ROOMS_SAVED": rooms_before - rooms_after,
            }
        )

    df_merge = pd.DataFrame(merged_results)
    df_key = pd.DataFrame(summary_key)

    df_day = (
        df_key.groupby("DATE", as_index=False)[["ROOMS_BEFORE", "ROOMS_AFTER", "ROOMS_SAVED"]]
        .sum()
        .sort_values("DATE")
    )

    return df_merge, df_key, df_day


def build_overall_summary(df_key: pd.DataFrame) -> pd.DataFrame:
    # số ca thi = số KEY (không đổi sau gộp)
    total_keys = int(df_key["KEY"].nunique(dropna=False))

    total_rooms_before = int(df_key["ROOMS_BEFORE"].sum())
    total_rooms_after = int(df_key["ROOMS_AFTER"].sum())
    total_rooms_saved = int(df_key["ROOMS_SAVED"].sum())

    pct_saved = (total_rooms_saved / total_rooms_before * 100) if total_rooms_before else 0.0

    return pd.DataFrame([{
        "TONG_SO_CA_THI": total_keys,
        "SO_PHONG_BAN_DAU": total_rooms_before,
        "SO_PHONG_SAU_GOP": total_rooms_after,
        "SO_PHONG_TIET_KIEM": total_rooms_saved,
        "PHAN_TRAM_TIET_KIEM_%": round(pct_saved, 2),
    }])


def main():
    df = pd.read_csv(INPUT_FILE, encoding="utf-8-sig")

    check_required_columns(df)

    df = parse_date_column(df)
    df = clean_numeric(df)

    if df["DATE_DT"].isna().any():
        print("⚠️ Some DATE values could not be parsed. Unique problematic values:")
        print(df.loc[df["DATE_DT"].isna(), "DATE"].unique())

    df_merge, df_key, df_day = merge_rooms(df)

    # overall summary
    df_tongket = build_overall_summary(df_key)

    # Export
    df_merge.to_csv("merge_suggestions.csv", index=False, encoding="utf-8-sig")
    df_key.to_csv("savings_by_key.csv", index=False, encoding="utf-8-sig")
    df_day.to_csv("savings_by_date.csv", index=False, encoding="utf-8-sig")
    df_tongket.to_csv("tongket.csv", index=False, encoding="utf-8-sig")

    print("\nCreated:")
    print(" - merge_suggestions.csv (detailed merges using EXAM CAPACITY)")
    print(" - savings_by_key.csv (stats per KEY)")
    print(" - savings_by_date.csv (daily totals sorted by DATE)")
    print(" - tongket.csv (overall summary)")

    print("\n=== OVERALL SUMMARY ===")
    print(df_tongket.to_string(index=False))

    print("\n=== Daily savings ===")
    print(df_day.to_string(index=False))


if __name__ == "__main__":
    main()
