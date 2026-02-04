# merge.py
# Build merge_suggestions.csv from allocation_plan.csv
#
# Input columns (allocation_plan.csv):
#   DATE_ONLY, TIME, CAMPUS, ROOM ID,
#   ROOM CAPACITY (preferred), ROOM EXAM CAPACITY (optional),
#   COURSE ID, ALLOCATED STUDENTS
#
# Output columns (merge_suggestions.csv):
#   DATE_ONLY, TIME, CAMPUS, TARGET ROOM,
#   ROOM CAPACITY, ROOM EXAM CAPACITY,
#   TOTAL STUDENTS, COURSES MERGED, UTILIZATION

import pandas as pd

IN_FILE = "allocation_plan.csv"
OUT_FILE = "merge_suggestions.csv"


def main():
    df = pd.read_csv(IN_FILE, encoding="utf-8-sig")

    base_required = [
        "DATE_ONLY", "TIME", "CAMPUS",
        "ROOM ID",
        "COURSE ID", "ALLOCATED STUDENTS",
    ]
    missing = [c for c in base_required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in {IN_FILE}: {missing}")

    # Prefer ROOM CAPACITY; fallback to ROOM EXAM CAPACITY
    has_room_cap = "ROOM CAPACITY" in df.columns
    has_exam_cap = "ROOM EXAM CAPACITY" in df.columns

    if not has_room_cap and not has_exam_cap:
        raise ValueError(
            f"{IN_FILE} must contain either 'ROOM CAPACITY' or 'ROOM EXAM CAPACITY'."
        )

    cap_col = "ROOM CAPACITY" if has_room_cap else "ROOM EXAM CAPACITY"
    if not has_room_cap:
        print("⚠️ WARNING: 'ROOM CAPACITY' not found. Fallback to 'ROOM EXAM CAPACITY' for UTILIZATION.")

    # numeric safety
    df["ALLOCATED STUDENTS"] = pd.to_numeric(df["ALLOCATED STUDENTS"], errors="coerce").fillna(0).astype(int)

    df[cap_col] = pd.to_numeric(df[cap_col], errors="coerce")
    df = df.dropna(subset=[cap_col]).copy()
    df[cap_col] = df[cap_col].astype(int)

    if has_exam_cap:
        df["ROOM EXAM CAPACITY"] = pd.to_numeric(df["ROOM EXAM CAPACITY"], errors="coerce")
        # keep as nullable; we won't drop rows by this column
        df["ROOM EXAM CAPACITY"] = df["ROOM EXAM CAPACITY"].astype("Int64")

    # ---- per (slot, room, course): sum chunks ----
    per_course = (
        df.groupby(["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID", "COURSE ID"], as_index=False)
          .agg(ALLOCATED=("ALLOCATED STUDENTS", "sum"))
    )

    # ---- per (slot, room): totals ----
    agg_dict = {
        "ROOM_CAP": (cap_col, "first"),
        "TOTAL_STUDENTS": ("ALLOCATED STUDENTS", "sum"),
    }
    if has_exam_cap:
        agg_dict["ROOM_EXAM_CAP"] = ("ROOM EXAM CAPACITY", "first")

    per_room = (
        df.groupby(["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID"], as_index=False)
          .agg(**agg_dict)
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

    # ---- utilization based on ROOM CAPACITY (preferred) ----
    out["UTILIZATION"] = out["TOTAL_STUDENTS"] / out["ROOM_CAP"]

    # ---- rename columns to requested output names ----
    out = out.rename(columns={
        "ROOM ID": "TARGET ROOM",
        "ROOM_CAP": "ROOM CAPACITY",
        "ROOM_EXAM_CAP": "ROOM EXAM CAPACITY",
    })

    # Ensure output columns exist (even if exam cap missing)
    if "ROOM EXAM CAPACITY" not in out.columns:
        out["ROOM EXAM CAPACITY"] = pd.NA

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
