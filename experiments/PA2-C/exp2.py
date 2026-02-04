import pandas as pd

# =========================================================
# Merge exam rooms (greedy bin packing) + add 3 dummy rooms
# and PRIORITIZE using dummy rooms as TARGET ROOM, correct CAMPUS:
# - NTD  @ CS2, EXAM CAPACITY = 300
# - H6-GD@ CS2, EXAM CAPACITY = 250
# - B5-GD@ CS1, EXAM CAPACITY = 130
#
# Requirements:
# - dummy available for every KEY (but only if same campus as that KEY)
# - ROOMS_BEFORE does NOT count dummy rooms
# - prioritize dummy (open dummy bins first)
#
# Output:
#   1) merge_suggestions.csv
#   2) savings_by_key.csv
#   3) savings_by_date.csv
#   4) tongket.csv
# =========================================================

INPUT_FILE = "phong_thi.csv"

STRICT_EXAMCAP_ONLY = False
STRICT_KEY_CONSISTENCY_CHECK = False

DUMMY_PREFIX = "__DUMMY__"

NEW_DUMMY_ROOMS = [
    {"ROOM ID": "NTD",   "CAMPUS": "CS2", "EXAM CAPACITY": 300},
    {"ROOM ID": "H6-GD", "CAMPUS": "CS2", "EXAM CAPACITY": 250},
    {"ROOM ID": "B5-GD", "CAMPUS": "CS1", "EXAM CAPACITY": 130},
]


def parse_date_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Robust DATE parsing:
    1) Excel serial numbers (numeric) -> datetime
    2) fallback dd/mm/yyyy strings
    """
    date_numeric = pd.to_numeric(df["DATE"], errors="coerce")
    df["DATE_DT"] = pd.to_datetime(date_numeric, unit="D", origin="1899-12-30", errors="coerce")

    mask_na = df["DATE_DT"].isna()
    df.loc[mask_na, "DATE_DT"] = pd.to_datetime(df.loc[mask_na, "DATE"], dayfirst=True, errors="coerce")

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


def norm_campus(x) -> str:
    s = str(x).strip().upper()
    if s == "1":
        return "CS1"
    if s == "2":
        return "CS2"
    return s


def is_dummy_course(course_id) -> bool:
    return str(course_id).startswith(DUMMY_PREFIX)


def add_dummy_rows_per_key(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add dummy rows for each KEY, matching campus only.
    Dummy has STUDENTS=0, unique COURSE ID per dummy room to avoid ok_distinct conflicts.
    """
    df2 = df.copy()
    df2["CAMPUS_NORM"] = df2["CAMPUS"].apply(norm_campus)

    keys = df2["KEY"].dropna().unique().tolist()

    dummy_rows = []
    for k in keys:
        g = df2[df2["KEY"] == k]
        if g.empty:
            continue

        campus_k = norm_campus(g.iloc[0]["CAMPUS"])
        date_k = g.iloc[0]["DATE"]
        time_k = g.iloc[0]["TIME"]

        for r in NEW_DUMMY_ROOMS:
            if norm_campus(r["CAMPUS"]) != campus_k:
                continue

            row = {c: pd.NA for c in df2.columns}
            row["KEY"] = k
            row["DATE"] = date_k
            row["TIME"] = time_k
            row["CAMPUS"] = campus_k

            row["ROOM ID"] = r["ROOM ID"]
            row["STUDENTS"] = 0

            # bin capacity for dummy
            row["EXAM CAPACITY"] = r["EXAM CAPACITY"]

            # CAPACITY: set = EXAM CAPACITY so fallback won't distort
            row["CAPACITY"] = r["EXAM CAPACITY"]

            # unique dummy course id per room
            row["COURSE ID"] = f"{DUMMY_PREFIX}{r['ROOM ID']}"

            dummy_rows.append(row)

    if dummy_rows:
        df2 = pd.concat([df2, pd.DataFrame(dummy_rows)], ignore_index=True)

    return df2


def merge_rooms(df: pd.DataFrame):
    merged_results = []
    summary_key = []

    # ROOMS_BEFORE excludes dummy
    df_original = df[~df["COURSE ID"].astype(str).str.startswith(DUMMY_PREFIX)].copy()
    rooms_before_by_key = df_original.groupby("KEY", dropna=False).size().to_dict()

    for key_val, group in df.groupby("KEY", dropna=False):
        rooms_before = int(rooms_before_by_key.get(key_val, 0))

        if STRICT_KEY_CONSISTENCY_CHECK and not group.empty:
            uniq_date = group["DATE_ONLY"].nunique(dropna=True)
            uniq_time = group["TIME"].nunique(dropna=True)
            uniq_campus = group["CAMPUS"].nunique(dropna=True)
            if uniq_date > 1 or uniq_time > 1 or uniq_campus > 1:
                print(
                    f"KEY '{key_val}' mixes sessions: "
                    f"dates={uniq_date}, times={uniq_time}, campus={uniq_campus}"
                )

        # prioritize dummy rows first (open dummy bins first)
        group = group.copy()
        group["__IS_DUMMY__"] = group["COURSE ID"].apply(is_dummy_course).astype(int)

        # dummy first, then largest classes
        group_sorted = group.sort_values(
            by=["__IS_DUMMY__", "STUDENTS"],
            ascending=[False, False],
        ).drop(columns=["__IS_DUMMY__"])

        bins = []

        for _, row in group_sorted.iterrows():
            placed = False
            course_id = str(row["COURSE ID"])
            n_sv = int(row["STUDENTS"])

            exam_cap = row["EXAM CAPACITY"]
            if pd.isna(exam_cap):
                if STRICT_EXAMCAP_ONLY:
                    exam_cap = 0
                else:
                    exam_cap = row["CAPACITY"]

            exam_cap = int(exam_cap) if not pd.isna(exam_cap) else 0

            # Try to fit into existing bins
            for b in bins:
                ok_distinct = course_id not in b["courses"]
                ok_capacity = (b["current"] + n_sv) <= b["exam_capacity"]
                if ok_distinct and ok_capacity:
                    b["items"].append(row)
                    b["courses"].add(course_id)
                    b["current"] += n_sv
                    placed = True
                    break

            # Otherwise create a new bin (dummy rows were processed first)
            if not placed:
                bins.append(
                    {
                        "target_room": str(row["ROOM ID"]),
                        "exam_capacity": exam_cap,
                        "current": n_sv,
                        "courses": {course_id},
                        "items": [row],
                    }
                )

        date_only = group_sorted.iloc[0]["DATE_ONLY"] if not group_sorted.empty else pd.NaT
        time_val = group_sorted.iloc[0]["TIME"] if not group_sorted.empty else pd.NA
        campus_val = norm_campus(group_sorted.iloc[0]["CAMPUS"]) if not group_sorted.empty else pd.NA

        for b in bins:
            courses_merged = ", ".join(
                [
                    f'{r["COURSE ID"]}({int(r["STUDENTS"])})'
                    for r in b["items"]
                    if not is_dummy_course(r["COURSE ID"])
                ]
            )

            merged_results.append(
                {
                    "KEY": key_val,
                    "DATE": date_only,
                    "TIME": time_val,
                    "CAMPUS": campus_val,
                    "TARGET ROOM": b["target_room"],
                    "EXAM CAPACITY": b["exam_capacity"],
                    "TOTAL STUDENTS": b["current"],
                    "COURSES MERGED": courses_merged,
                    "UTILIZATION": (b["current"] / b["exam_capacity"]) if b["exam_capacity"] else 0.0,
                }
            )

        rooms_after = len(bins)
        summary_key.append(
            {
                "DATE": date_only,
                "KEY": key_val,
                "ROOMS_BEFORE": rooms_before,               # excludes dummy
                "ROOMS_AFTER": rooms_after,                 # includes dummy bins if used
                "ROOMS_SAVED": rooms_before - rooms_after,  # can be negative
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
    total_keys = int(df_key["KEY"].nunique(dropna=False)) if not df_key.empty else 0
    total_rooms_before = int(df_key["ROOMS_BEFORE"].sum()) if not df_key.empty else 0
    total_rooms_after = int(df_key["ROOMS_AFTER"].sum()) if not df_key.empty else 0
    total_rooms_saved = int(df_key["ROOMS_SAVED"].sum()) if not df_key.empty else 0
    pct_saved = (total_rooms_saved / total_rooms_before * 100) if total_rooms_before else 0.0

    return pd.DataFrame([{
        "TOTAL_EXAM_SLOTS_(KEY)": total_keys,
        "TOTAL_ROOMS_BEFORE": total_rooms_before,
        "TOTAL_ROOMS_AFTER": total_rooms_after,
        "TOTAL_ROOMS_SAVED": total_rooms_saved,
        "PCT_ROOMS_SAVED_%": round(pct_saved, 2),
        "DUMMY_ROOMS": "NTD@CS2(300); H6-GD@CS2(250); B5-GD@CS1(130)",
        "DUMMY_PRIORITY": "YES",
        "NOTE": "ROOMS_BEFORE excludes dummy rows",
    }])


def main():
    df = pd.read_csv(INPUT_FILE, encoding="utf-8-sig")

    check_required_columns(df)

    df = parse_date_column(df)
    df = clean_numeric(df)

    # add dummy per KEY (correct campus)
    df = add_dummy_rows_per_key(df)

    if df["DATE_DT"].isna().any():
        print("⚠️ Some DATE values could not be parsed. Unique problematic values:")
        print(df.loc[df["DATE_DT"].isna(), "DATE"].unique())

    df_merge, df_key, df_day = merge_rooms(df)
    df_tongket = build_overall_summary(df_key)

    df_merge.to_csv("merge_suggestions.csv", index=False, encoding="utf-8-sig")
    df_key.to_csv("savings_by_key.csv", index=False, encoding="utf-8-sig")
    df_day.to_csv("savings_by_date.csv", index=False, encoding="utf-8-sig")
    df_tongket.to_csv("tongket.csv", index=False, encoding="utf-8-sig")

    print("\nCreated:")
    print(" - merge_suggestions.csv (detailed merges using EXAM CAPACITY)")
    print(" - savings_by_key.csv (stats per KEY, ROOMS_BEFORE excludes dummy)")
    print(" - savings_by_date.csv (daily totals sorted by DATE)")
    print(" - tongket.csv (overall summary)")

    print("\n=== OVERALL SUMMARY ===")
    print(df_tongket.to_string(index=False))

    print("\n=== Daily savings ===")
    print(df_day.to_string(index=False))


if __name__ == "__main__":
    main()
