# merge.py
# Build merge_suggestions.csv from allocation_plan.csv
#
# Input columns (allocation_plan.csv):
#   DATE_ONLY, TIME, CAMPUS, ROOM ID, ROOM EXAM CAPACITY, COURSE ID, ALLOCATED STUDENTS
#
# Output columns (merge_suggestions.csv):
#   DATE_ONLY, TIME, CAMPUS, TARGET ROOM, ROOM EXAM CAPACITY, TOTAL STUDENTS, COURSES MERGED, UTILIZATION

import pandas as pd

IN_FILE = "allocation_plan.csv"
OUT_FILE = "merge_suggestions.csv"


def main():
    df = pd.read_csv(IN_FILE, encoding="utf-8-sig")

    required = [
        "DATE_ONLY", "TIME", "CAMPUS",
        "ROOM ID", "ROOM EXAM CAPACITY",
        "COURSE ID", "ALLOCATED STUDENTS"
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in {IN_FILE}: {missing}")

    # numeric safety
    df["ROOM EXAM CAPACITY"] = pd.to_numeric(df["ROOM EXAM CAPACITY"], errors="coerce")
    df["ALLOCATED STUDENTS"] = pd.to_numeric(df["ALLOCATED STUDENTS"], errors="coerce").fillna(0).astype(int)
    df = df.dropna(subset=["ROOM EXAM CAPACITY"]).copy()
    df["ROOM EXAM CAPACITY"] = df["ROOM EXAM CAPACITY"].astype(int)

    # ---- per (slot, room, course): sum chunks ----
    per_course = (
        df.groupby(["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID", "COURSE ID"], as_index=False)
          .agg(ALLOCATED=("ALLOCATED STUDENTS", "sum"))
    )

    # ---- per (slot, room): totals ----
    per_room = (
        df.groupby(["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID"], as_index=False)
          .agg(
              ROOM_EXAM_CAPACITY=("ROOM EXAM CAPACITY", "first"),
              TOTAL_STUDENTS=("ALLOCATED STUDENTS", "sum"),
          )
    )

    # ---- build "COURSES MERGED" string ----
    per_course = per_course.sort_values(
        ["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID", "ALLOCATED"],
        ascending=[True, True, True, True, False],
    )
    per_course["COURSE_ITEM"] = per_course.apply(
        lambda r: f"{r['COURSE ID']}({int(r['ALLOCATED'])})",
        axis=1
    )

    courses_join = (
        per_course.groupby(["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID"])["COURSE_ITEM"]
                 .agg(lambda s: ", ".join(s.tolist()))
                 .reset_index(name="COURSES MERGED")
    )

    out = per_room.merge(courses_join, on=["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID"], how="left")

    out["UTILIZATION"] = out["TOTAL_STUDENTS"] / out["ROOM_EXAM_CAPACITY"]

    out = out.rename(columns={
        "ROOM ID": "TARGET ROOM",
        "ROOM_EXAM_CAPACITY": "ROOM EXAM CAPACITY",
    })

    out = out.sort_values(
        ["DATE_ONLY", "TIME", "CAMPUS", "TOTAL_STUDENTS"],
        ascending=[True, True, True, False],
    )

    out.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")

    print(f"Created: {OUT_FILE}")
    print(f"Rows: {len(out)}")
    print("\nPreview (top 15):")
    print(out.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
