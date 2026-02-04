import pandas as pd

# =========================================================
# MERGE EXAM ROOMS (greedy bin packing) with constraints:
# - Group by KEY_CA
# - Only merge if different COURSE ID (F_MAMH)
# - Capacity constraint uses EXAM CAPACITY (SUC_CHUA)
#
# Outputs:
# 1) merge_suggestions.csv          (detailed merged rooms)
# 2) savings_by_key.csv             (stats per KEY_CA)
# 3) savings_by_date.csv            (stats per DATE)
# 4) tongket.csv                    (overall summary)
# =========================================================

INPUT_FILE = "phong_thi.csv"

OUT_MERGE = "merge_suggestions.csv"
OUT_KEY = "savings_by_key.csv"
OUT_DATE = "savings_by_date.csv"
OUT_TONGKET = "tongket.csv"

# ===== 1) Load data =====
df = pd.read_csv(INPUT_FILE, sep=",", encoding="utf-8-sig")

# ===== 2) Parse DATE (Excel serial -> date) with fallback dd/mm/yyyy =====
df["DATE_DT"] = pd.to_datetime(df["NGAYTHI"], unit="D", origin="1899-12-30", errors="coerce")
mask_na = df["DATE_DT"].isna()
df.loc[mask_na, "DATE_DT"] = pd.to_datetime(df.loc[mask_na, "NGAYTHI"], dayfirst=True, errors="coerce")
df["DATE_ONLY"] = df["DATE_DT"].dt.date

# ===== 3) Merge rooms by KEY_CA (course must be distinct) =====
merged_rows = []
summary_rows = []

for key_val, group in df.groupby("KEY_CA", dropna=False):
    rooms_before = len(group)

    # pack larger classes first
    group_sorted = group.sort_values("F_SOLUONG", ascending=False)

    # each bin = one target room
    bins = []

    for _, row in group_sorted.iterrows():
        placed = False
        course_id = row["F_MAMH"]
        students = int(row["F_SOLUONG"])
        exam_capacity = int(row["SUC_CHUA"])

        for b in bins:
            ok_capacity = (b["current_students"] + students) <= b["exam_capacity"]
            ok_distinct = course_id not in b["courses"]  # only merge different courses

            if ok_capacity and ok_distinct:
                b["items"].append(row)
                b["courses"].add(course_id)
                b["current_students"] += students
                placed = True
                break

        if not placed:
            bins.append(
                {
                    "target_room": row["F_TENPHMOI"],
                    "exam_capacity": exam_capacity,
                    "current_students": students,
                    "courses": {course_id},
                    "items": [row],
                }
            )

    # detailed merge output
    date_only = group_sorted.iloc[0]["DATE_ONLY"]
    for b in bins:
        merged_rows.append(
            {
                "KEY": key_val,
                "DATE": date_only,
                "TARGET ROOM": b["target_room"],
                "ROOM EXAM CAPACITY": b["exam_capacity"],
                "TOTAL STUDENTS": b["current_students"],
                "COURSES MERGED": ", ".join(
                    [f'{r["F_MAMH"]}({int(r["F_SOLUONG"])})' for r in b["items"]]
                ),
                "UTILIZATION": (b["current_students"] / b["exam_capacity"]) if b["exam_capacity"] else 0.0,
            }
        )

    rooms_after = len(bins)
    summary_rows.append(
        {
            "DATE": date_only,
            "KEY": key_val,
            "ROOMS_BEFORE": rooms_before,
            "ROOMS_AFTER": rooms_after,
            "ROOMS_SAVED": rooms_before - rooms_after,
        }
    )

df_merge = pd.DataFrame(merged_rows)
df_key = pd.DataFrame(summary_rows)

# ===== 4) Daily savings =====
df_day = (
    df_key.groupby("DATE", as_index=False)[["ROOMS_BEFORE", "ROOMS_AFTER", "ROOMS_SAVED"]]
    .sum()
    .sort_values("DATE")
)

# ===== 5) Overall summary (tongket.csv) =====
total_keys = int(df_key["KEY"].nunique(dropna=False))
total_rooms_before = int(df_key["ROOMS_BEFORE"].sum())
total_rooms_after = int(df_key["ROOMS_AFTER"].sum())
total_rooms_saved = int(df_key["ROOMS_SAVED"].sum())
pct_saved = (total_rooms_saved / total_rooms_before * 100) if total_rooms_before else 0.0

df_tongket = pd.DataFrame([{
    "TOTAL_EXAM_SLOTS_(KEY)": total_keys,
    "TOTAL_ROOMS_BEFORE": total_rooms_before,
    "TOTAL_ROOMS_AFTER": total_rooms_after,
    "TOTAL_ROOMS_SAVED": total_rooms_saved,
    "PCT_ROOMS_SAVED_%": round(pct_saved, 2),
}])

# ===== 6) Export =====
df_merge.to_csv(OUT_MERGE, index=False, encoding="utf-8-sig")
df_key.to_csv(OUT_KEY, index=False, encoding="utf-8-sig")
df_day.to_csv(OUT_DATE, index=False, encoding="utf-8-sig")
df_tongket.to_csv(OUT_TONGKET, index=False, encoding="utf-8-sig")

# ===== 7) Print summary =====
print("\nCreated:")
print(f" - {OUT_MERGE} (detailed merged rooms)")
print(f" - {OUT_KEY} (stats per KEY)")
print(f" - {OUT_DATE} (daily totals sorted by DATE)")
print(f" - {OUT_TONGKET} (overall summary)")

print("\n=== OVERALL SUMMARY ===")
print(df_tongket.to_string(index=False))

print("\n=== DAILY SAVINGS ===")
print(df_day.to_string(index=False))
