import pandas as pd

# =========================================================
# PRIORITIZE PACKING INTO 2 DUMMY ROOMS, CORRECT CAMPUS:
# - H6-GD only in CS2 (EXAM CAPACITY = 250)
# - B5-GD only in CS1 (EXAM CAPACITY = 130)
#
# Approach:
# - For each KEY (KEY_CA), only add the dummy room matching that KEY's CAMPUS (COSO).
# - Prioritize dummy rooms by sorting dummy rows first so bins open with dummy rooms.
# - ROOMS_BEFORE does NOT count dummy rooms.
#
# Input (phong_thi.csv) expected columns used:
#   KEY_CA, NGAYTHI, COSO, F_TENPHMOI, SUC_CHUA, F_MAMH, F_SOLUONG
#
# Outputs:
#  - merge_suggestions.csv        (detailed merged rooms)
#  - savings_by_key.csv           (stats per KEY)
#  - savings_by_date.csv          (stats per DATE)
#  - tongket.csv                  (overall summary)
# =========================================================

INPUT_FILE = "phong_thi.csv"

OUT_MERGE = "merge_suggestions.csv"
OUT_KEY = "savings_by_key.csv"
OUT_DATE = "savings_by_date.csv"
OUT_TONGKET = "tongket.csv"

NEW_ROOMS = [
    {"ROOM ID": "H6-GD", "ROOM EXAM CAPACITY": 250, "CAMPUS": "CS2"},
    {"ROOM ID": "B5-GD", "ROOM EXAM CAPACITY": 130, "CAMPUS": "CS1"},
]
DUMMY_PREFIX = "__DUMMY__"


def parse_exam_date(df: pd.DataFrame) -> pd.DataFrame:
    # Excel serial -> date, fallback dd/mm/yyyy
    df["DATE_DT"] = pd.to_datetime(df["NGAYTHI"], unit="D", origin="1899-12-30", errors="coerce")
    mask_na = df["DATE_DT"].isna()
    df.loc[mask_na, "DATE_DT"] = pd.to_datetime(df.loc[mask_na, "NGAYTHI"], dayfirst=True, errors="coerce")
    df["DATE_ONLY"] = df["DATE_DT"].dt.date
    return df


def normalize_campus(val) -> str:
    """
    Input COSO could be: CS1/CS2 or 1/2 (or '1', '2').
    Return: 'CS1' or 'CS2' or '' if unknown.
    """
    s = str(val).strip().upper()
    if s in {"1", "CS1"}:
        return "CS1"
    if s in {"2", "CS2"}:
        return "CS2"
    return s


def is_dummy_course(course_id) -> bool:
    return str(course_id).startswith(DUMMY_PREFIX)


def main():
    # ===== 1) Load =====
    df = pd.read_csv(INPUT_FILE, sep=",", encoding="utf-8-sig")

    # minimal column checks
    required = ["KEY_CA", "NGAYTHI", "F_TENPHMOI", "SUC_CHUA", "F_MAMH", "F_SOLUONG"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in {INPUT_FILE}: {missing}")

    if "COSO" not in df.columns:
        raise ValueError("Missing column 'COSO' (campus) in phong_thi.csv. Needed to place dummy rooms correctly.")

    # ===== 2) Parse DATE =====
    df = parse_exam_date(df)

    # numeric safety
    df["F_SOLUONG"] = pd.to_numeric(df["F_SOLUONG"], errors="coerce").fillna(0).astype(int)
    df["SUC_CHUA"] = pd.to_numeric(df["SUC_CHUA"], errors="coerce").fillna(0).astype(int)
    df["F_MAMH"] = df["F_MAMH"].astype(str)
    df["F_TENPHMOI"] = df["F_TENPHMOI"].astype(str)

    # ===== 2.1) Keep original to compute ROOMS_BEFORE (exclude dummy) =====
    df_original = df.copy()

    rooms_before_by_key = (
        df_original.dropna(subset=["KEY_CA"])
        .groupby("KEY_CA")
        .size()
        .to_dict()
    )

    # ===== 2.2) Add dummy rows per KEY, only matching campus =====
    key_list = df_original["KEY_CA"].dropna().unique().tolist()
    dummy_rows = []

    for key_val in key_list:
        rep = df_original.loc[df_original["KEY_CA"] == key_val].iloc[0]
        key_campus = normalize_campus(rep.get("COSO", ""))

        for r in NEW_ROOMS:
            if r["CAMPUS"] != key_campus:
                continue

            # create a row with same columns
            row = {c: pd.NA for c in df_original.columns}

            row["KEY_CA"] = key_val
            row["NGAYTHI"] = rep.get("NGAYTHI", pd.NA)
            row["DATE_DT"] = rep.get("DATE_DT", pd.NA)
            row["DATE_ONLY"] = rep.get("DATE_ONLY", pd.NA)

            row["COSO"] = r["CAMPUS"]          # normalized campus
            row["F_TENPHMOI"] = r["ROOM ID"]
            row["SUC_CHUA"] = int(r["ROOM EXAM CAPACITY"])  # treat as exam capacity

            # dummy course id (unique per dummy room)
            row["F_MAMH"] = f"{DUMMY_PREFIX}{r['ROOM ID']}"
            row["F_SOLUONG"] = 0

            dummy_rows.append(row)

    if dummy_rows:
        df = pd.concat([df_original, pd.DataFrame(dummy_rows)], ignore_index=True)
    else:
        df = df_original

    # ===== 3) Merge rooms by KEY (greedy bin packing; dummy first) =====
    merged_results = []
    summary_rows = []

    for key_val, group in df.groupby("KEY_CA", dropna=False):
        if pd.isna(key_val):
            continue

        rooms_before = int(rooms_before_by_key.get(key_val, 0))  # EXCLUDE dummy

        group = group.copy()
        group["__IS_DUMMY__"] = group["F_MAMH"].apply(is_dummy_course).astype(int)

        # Dummy rows first -> open bins with dummy rooms before others
        # Then larger classes first
        group_sorted = group.sort_values(
            by=["__IS_DUMMY__", "F_SOLUONG"],
            ascending=[False, False]
        ).drop(columns=["__IS_DUMMY__"])

        bins = []
        for _, row in group_sorted.iterrows():
            placed = False
            course_id = str(row["F_MAMH"])
            students = int(row["F_SOLUONG"])
            room_exam_capacity = int(row["SUC_CHUA"])
            room_name = str(row["F_TENPHMOI"])

            for b in bins:
                ok_capacity = (b["current_students"] + students) <= b["room_exam_capacity"]
                ok_distinct = course_id not in b["courses"]  # only merge different courses
                if ok_capacity and ok_distinct:
                    b["items"].append(row)
                    b["courses"].add(course_id)
                    b["current_students"] += students
                    placed = True
                    break

            if not placed:
                bins.append({
                    "target_room": room_name,
                    "room_exam_capacity": room_exam_capacity,
                    "current_students": students,
                    "courses": {course_id},
                    "items": [row],
                })

        date_only = group_sorted.iloc[0]["DATE_ONLY"]
        time_val = group_sorted.iloc[0].get("GIO", pd.NA)  # optional if exists
        campus_val = normalize_campus(group_sorted.iloc[0].get("COSO", ""))

        # detailed output (exclude dummy courses from COURSE LIST)
        for b in bins:
            course_list = ", ".join(
                [
                    f'{r["F_MAMH"]}({int(r["F_SOLUONG"])})'
                    for r in b["items"]
                    if not is_dummy_course(r["F_MAMH"])
                ]
            )

            merged_results.append({
                "KEY": key_val,
                "DATE_ONLY": date_only,
                "CAMPUS": campus_val,
                "TARGET ROOM": b["target_room"],
                "ROOM EXAM CAPACITY": b["room_exam_capacity"],
                "TOTAL STUDENTS": b["current_students"],
                "COURSES MERGED": course_list,
                "UTILIZATION": (b["current_students"] / b["room_exam_capacity"]) if b["room_exam_capacity"] else 0.0,
            })

        rooms_after = len(bins)  # includes dummy bins if they stayed empty
        rooms_saved = rooms_before - rooms_after

        summary_rows.append({
            "DATE_ONLY": date_only,
            "KEY": key_val,
            "CAMPUS": campus_val,
            "ROOMS_BEFORE": rooms_before,
            "ROOMS_AFTER": rooms_after,
            "ROOMS_SAVED": rooms_saved
        })

    df_merge = pd.DataFrame(merged_results)
    df_key = pd.DataFrame(summary_rows)

    # ===== 4) Daily savings =====
    df_day = (
        df_key.groupby("DATE_ONLY", as_index=False)[["ROOMS_BEFORE", "ROOMS_AFTER", "ROOMS_SAVED"]]
        .sum()
        .sort_values("DATE_ONLY")
    )

    # ===== 5) Overall summary =====
    total_keys = int(df_key["KEY"].nunique(dropna=False)) if not df_key.empty else 0
    total_rooms_before = int(df_key["ROOMS_BEFORE"].sum()) if not df_key.empty else 0
    total_rooms_after = int(df_key["ROOMS_AFTER"].sum()) if not df_key.empty else 0
    total_rooms_saved = int(df_key["ROOMS_SAVED"].sum()) if not df_key.empty else 0
    pct_saved = (total_rooms_saved / total_rooms_before * 100) if total_rooms_before else 0.0

    df_tongket = pd.DataFrame([{
        "TOTAL_EXAM_SLOTS_(KEY)": total_keys,
        "TOTAL_ROOMS_BEFORE": total_rooms_before,
        "TOTAL_ROOMS_AFTER": total_rooms_after,
        "TOTAL_ROOMS_SAVED": total_rooms_saved,
        "PCT_ROOMS_SAVED_%": round(pct_saved, 2),
        "DUMMY_PRIORITY": "YES",
        "DUMMY_ROOMS": "H6-GD@CS2(250); B5-GD@CS1(130)",
    }])

    # ===== 6) Export =====
    df_merge.to_csv(OUT_MERGE, index=False, encoding="utf-8-sig")
    df_key.to_csv(OUT_KEY, index=False, encoding="utf-8-sig")
    df_day.to_csv(OUT_DATE, index=False, encoding="utf-8-sig")
    df_tongket.to_csv(OUT_TONGKET, index=False, encoding="utf-8-sig")

    # ===== 7) Print =====
    print("\nCreated:")
    print(f" - {OUT_MERGE} (detailed merged rooms)")
    print(f" - {OUT_KEY} (stats per KEY)")
    print(f" - {OUT_DATE} (daily totals sorted by DATE)")
    print(f" - {OUT_TONGKET} (overall summary)")

    print("\n=== OVERALL SUMMARY ===")
    print(df_tongket.to_string(index=False))

    print("\n=== DAILY SAVINGS ===")
    print(df_day.to_string(index=False))


if __name__ == "__main__":
    main()
