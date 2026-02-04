import pandas as pd
from typing import Dict, List, Any, Tuple

# =========================================================
# ROOM PACKING WITH TWO CAPACITIES + OVERALL SUMMARY (tongket.csv)
# + ADD 2 EXTRA ROOMS ALWAYS AVAILABLE:
#   - CS1: B5-GD (CAP=130, EXAM CAP=130)
#   - CS2: H6-GD (CAP=250, EXAM CAP=250)
# =========================================================

STUDENTS_FILE = "students_by_course_datetime_campus.csv"
ROOMS_FILE = "rooms_capacity_campus.csv"

OUT_ALLOC = "allocation_plan.csv"
OUT_ROOM_SUMMARY = "allocation_room_summary.csv"
OUT_UNASSIGNED = "allocation_unassigned.csv"
OUT_ROOMS_USED_PER_DAY = "rooms_used_per_day_summary.csv"
OUT_TONGKET = "tongket.csv"

CAMPUSES = ["CS1", "CS2"]


def load_students(students_path: str) -> pd.DataFrame:
    df = pd.read_csv(students_path, encoding="utf-8-sig")

    required = ["COURSE ID", "DATE_ONLY", "TIME"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing column '{col}' in {students_path}")

    for campus_col in CAMPUSES:
        if campus_col not in df.columns:
            df[campus_col] = 0

    df["CS1"] = pd.to_numeric(df["CS1"], errors="coerce").fillna(0).astype(int)
    df["CS2"] = pd.to_numeric(df["CS2"], errors="coerce").fillna(0).astype(int)
    df["COURSE ID"] = df["COURSE ID"].astype(str)
    return df


def load_rooms(rooms_path: str) -> pd.DataFrame:
    df = pd.read_csv(rooms_path, encoding="utf-8-sig")

    required = ["ROOM ID", "CAPACITY", "EXAM CAPACITY", "CAMPUS_NORM"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing column '{col}' in {rooms_path}")

    # Optional: exclude conflict rooms
    if "CAMPUS_CONFLICT" in df.columns:
        df["CAMPUS_CONFLICT"] = df["CAMPUS_CONFLICT"].astype(str).str.upper().str.strip()
        df = df[df["CAMPUS_CONFLICT"] != "TRUE"].copy()

    df["CAPACITY"] = pd.to_numeric(df["CAPACITY"], errors="coerce")
    df["EXAM CAPACITY"] = pd.to_numeric(df["EXAM CAPACITY"], errors="coerce")

    df = df.dropna(subset=["CAPACITY", "EXAM CAPACITY"]).copy()
    df["CAPACITY"] = df["CAPACITY"].astype(int)
    df["EXAM CAPACITY"] = df["EXAM CAPACITY"].astype(int)

    df["ROOM ID"] = df["ROOM ID"].astype(str).str.strip()
    df["CAMPUS_NORM"] = df["CAMPUS_NORM"].astype(str).str.strip()
    return df


def add_extra_rooms_always_available(rooms_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 2 always-available rooms (if not already present):
      - CS1: B5-GD cap=130 exam_cap=130
      - CS2: H6-GD cap=250 exam_cap=250

    Notes:
      - If a room already exists in rooms_df (same ROOM ID), we DO NOT add a duplicate.
      - If it exists but campus differs, we keep the existing one (to avoid silently changing data).
    """
    extra = pd.DataFrame(
        [
            {"ROOM ID": "B5-GD", "CAPACITY": 130, "EXAM CAPACITY": 130, "CAMPUS_NORM": "CS1"},
            {"ROOM ID": "H6-GD", "CAPACITY": 250, "EXAM CAPACITY": 250, "CAMPUS_NORM": "CS2"},
        ]
    )

    # Normalize
    rooms_df = rooms_df.copy()
    rooms_df["ROOM ID"] = rooms_df["ROOM ID"].astype(str).str.strip()
    rooms_df["CAMPUS_NORM"] = rooms_df["CAMPUS_NORM"].astype(str).str.strip()

    existing = set(rooms_df["ROOM ID"].tolist())

    to_add = extra[~extra["ROOM ID"].isin(existing)].copy()
    if not to_add.empty:
        rooms_df = pd.concat([rooms_df, to_add], ignore_index=True)

    return rooms_df


def split_allocate_fill_rooms(
    demands: List[Dict[str, Any]],
    rooms: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    remaining: Dict[str, int] = {d["course_id"]: int(d["students"]) for d in demands}
    meta: Dict[str, Dict[str, Any]] = {d["course_id"]: d for d in demands}

    def sorted_courses() -> List[str]:
        return sorted(
            [cid for cid, rem in remaining.items() if rem > 0],
            key=lambda cid: remaining[cid],
            reverse=True,
        )

    rooms_sorted = sorted(rooms, key=lambda r: int(r["cap"]), reverse=True)

    allocations: List[Dict[str, Any]] = []

    for r in rooms_sorted:
        room_id = r["room_id"]
        room_cap = int(r["cap"])
        room_exam_cap = int(r["exam_cap"])

        room_remaining_cap = room_cap
        if room_remaining_cap <= 0:
            continue

        for cid in sorted_courses():
            if room_remaining_cap <= 0:
                break

            rem_students = remaining[cid]
            if rem_students <= 0:
                continue

            chunk = min(rem_students, room_remaining_cap, room_exam_cap)
            if chunk <= 0:
                continue

            allocations.append(
                {
                    "DATE_ONLY": meta[cid]["date"],
                    "TIME": meta[cid]["time"],
                    "CAMPUS": meta[cid]["campus"],
                    "ROOM ID": room_id,
                    "ROOM CAPACITY": room_cap,
                    "ROOM EXAM CAPACITY": room_exam_cap,
                    "COURSE ID": cid,
                    "ALLOCATED STUDENTS": int(chunk),
                }
            )

            remaining[cid] -= int(chunk)
            room_remaining_cap -= int(chunk)

    unassigned: List[Dict[str, Any]] = []
    for cid, rem in remaining.items():
        if rem > 0:
            d = meta[cid]
            unassigned.append(
                {
                    "DATE_ONLY": d["date"],
                    "TIME": d["time"],
                    "CAMPUS": d["campus"],
                    "COURSE ID": cid,
                    "UNASSIGNED STUDENTS": int(rem),
                    "reason": "Not enough total room CAPACITY in this slot/campus",
                }
            )

    return allocations, unassigned


def build_overall_summary(
    students_df: pd.DataFrame,
    alloc_out: pd.DataFrame,
    unassigned_out: pd.DataFrame,
    rooms_df: pd.DataFrame,
    rooms_used_pivot: pd.DataFrame,
) -> pd.DataFrame:
    demand_cs1 = int(students_df["CS1"].sum())
    demand_cs2 = int(students_df["CS2"].sum())
    demand_total = demand_cs1 + demand_cs2

    allocated_total = int(alloc_out["ALLOCATED STUDENTS"].sum()) if not alloc_out.empty else 0
    allocated_cs1 = int(alloc_out.loc[alloc_out["CAMPUS"] == "CS1", "ALLOCATED STUDENTS"].sum()) if not alloc_out.empty else 0
    allocated_cs2 = int(alloc_out.loc[alloc_out["CAMPUS"] == "CS2", "ALLOCATED STUDENTS"].sum()) if not alloc_out.empty else 0

    unassigned_total = int(unassigned_out["UNASSIGNED STUDENTS"].sum()) if not unassigned_out.empty else 0
    unassigned_cs1 = int(unassigned_out.loc[unassigned_out["CAMPUS"] == "CS1", "UNASSIGNED STUDENTS"].sum()) if not unassigned_out.empty else 0
    unassigned_cs2 = int(unassigned_out.loc[unassigned_out["CAMPUS"] == "CS2", "UNASSIGNED STUDENTS"].sum()) if not unassigned_out.empty else 0

    pct_allocated = (allocated_total / demand_total * 100) if demand_total else 0.0
    pct_unassigned = (unassigned_total / demand_total * 100) if demand_total else 0.0

    num_slots = int(students_df.groupby(["DATE_ONLY", "TIME"]).ngroups)

    rooms_inventory_cs1 = int((rooms_df["CAMPUS_NORM"] == "CS1").sum())
    rooms_inventory_cs2 = int((rooms_df["CAMPUS_NORM"] == "CS2").sum())
    rooms_inventory_total = rooms_inventory_cs1 + rooms_inventory_cs2

    if rooms_used_pivot is not None and not rooms_used_pivot.empty:
        total_room_slots_used = int(rooms_used_pivot["TOTAL_ROOM_SLOTS_USED"].sum()) if "TOTAL_ROOM_SLOTS_USED" in rooms_used_pivot.columns else 0
        total_room_slots_used_cs1 = int(rooms_used_pivot["CS1"].sum()) if "CS1" in rooms_used_pivot.columns else 0
        total_room_slots_used_cs2 = int(rooms_used_pivot["CS2"].sum()) if "CS2" in rooms_used_pivot.columns else 0
        peak_room_slots_used = int(rooms_used_pivot["TOTAL_ROOM_SLOTS_USED"].max()) if "TOTAL_ROOM_SLOTS_USED" in rooms_used_pivot.columns else 0
    else:
        total_room_slots_used = 0
        total_room_slots_used_cs1 = 0
        total_room_slots_used_cs2 = 0
        peak_room_slots_used = 0

    if alloc_out is not None and not alloc_out.empty:
        room_slot_sum = (
            alloc_out.groupby(["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID"], as_index=False)
            .agg(
                ROOM_CAPACITY=("ROOM CAPACITY", "first"),
                TOTAL_STUDENTS=("ALLOCATED STUDENTS", "sum"),
            )
        )
        total_capacity_used = int(room_slot_sum["ROOM_CAPACITY"].sum())
        total_students_in_used = int(room_slot_sum["TOTAL_STUDENTS"].sum())
        weighted_util = (total_students_in_used / total_capacity_used) if total_capacity_used else 0.0
    else:
        total_capacity_used = 0
        total_students_in_used = 0
        weighted_util = 0.0

    return pd.DataFrame([{
        "NUM_SLOTS_(DATE_ONLY,TIME)": num_slots,

        "DEMAND_CS1": demand_cs1,
        "DEMAND_CS2": demand_cs2,
        "DEMAND_TOTAL": demand_total,

        "ALLOCATED_CS1": allocated_cs1,
        "ALLOCATED_CS2": allocated_cs2,
        "ALLOCATED_TOTAL": allocated_total,

        "UNASSIGNED_CS1": unassigned_cs1,
        "UNASSIGNED_CS2": unassigned_cs2,
        "UNASSIGNED_TOTAL": unassigned_total,

        "PCT_ALLOCATED_%": round(pct_allocated, 2),
        "PCT_UNASSIGNED_%": round(pct_unassigned, 2),

        "ROOMS_INVENTORY_CS1": rooms_inventory_cs1,
        "ROOMS_INVENTORY_CS2": rooms_inventory_cs2,
        "ROOMS_INVENTORY_TOTAL": rooms_inventory_total,

        "ROOM_SLOTS_USED_CS1_SUM": total_room_slots_used_cs1,
        "ROOM_SLOTS_USED_CS2_SUM": total_room_slots_used_cs2,
        "ROOM_SLOTS_USED_TOTAL_SUM": total_room_slots_used,

        "ROOM_SLOTS_USED_PEAK_PER_DAY": peak_room_slots_used,

        "TOTAL_CAPACITY_USED_SUM": total_capacity_used,
        "TOTAL_STUDENTS_IN_USED_ROOMS_SUM": total_students_in_used,
        "WEIGHTED_UTILIZATION_USED_ROOMS": round(float(weighted_util), 4),
    }])


def main():
    students_df = load_students(STUDENTS_FILE)
    rooms_df = load_rooms(ROOMS_FILE)

    # ✅ Add 2 extra rooms (always available)
    rooms_df = add_extra_rooms_always_available(rooms_df)

    rooms_by_campus: Dict[str, List[Dict[str, Any]]] = {}
    for campus, g in rooms_df.groupby("CAMPUS_NORM"):
        rooms_by_campus[campus] = (
            g.sort_values("CAPACITY", ascending=False)[["ROOM ID", "CAPACITY", "EXAM CAPACITY"]]
            .to_dict("records")
        )

    all_allocations: List[Dict[str, Any]] = []
    all_unassigned: List[Dict[str, Any]] = []

    for (date_only, time_val), slot in students_df.groupby(["DATE_ONLY", "TIME"]):
        for campus in CAMPUSES:
            if campus not in rooms_by_campus:
                continue

            demands: List[Dict[str, Any]] = []
            for _, row in slot.iterrows():
                n = int(row[campus])
                if n <= 0:
                    continue
                demands.append(
                    {
                        "course_id": str(row["COURSE ID"]),
                        "students": n,
                        "date": date_only,
                        "time": time_val,
                        "campus": campus,
                    }
                )
            if not demands:
                continue

            rooms = [
                {"room_id": str(r["ROOM ID"]), "cap": int(r["CAPACITY"]), "exam_cap": int(r["EXAM CAPACITY"])}
                for r in rooms_by_campus[campus]
            ]

            allocations, unassigned = split_allocate_fill_rooms(demands, rooms)
            all_allocations.extend(allocations)
            all_unassigned.extend(unassigned)

    alloc_out = pd.DataFrame(all_allocations)
    if not alloc_out.empty:
        alloc_out = alloc_out.sort_values(["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID", "COURSE ID"])
    alloc_out.to_csv(OUT_ALLOC, index=False, encoding="utf-8-sig")

    if not alloc_out.empty:
        room_sum = (
            alloc_out.groupby(["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID"], as_index=False)
            .agg(
                ROOM_CAPACITY=("ROOM CAPACITY", "first"),
                ROOM_EXAM_CAPACITY=("ROOM EXAM CAPACITY", "first"),
                TOTAL_STUDENTS=("ALLOCATED STUDENTS", "sum"),
                NUM_MODULES=("COURSE ID", "nunique"),
            )
        )
        room_sum["UTILIZATION"] = room_sum["TOTAL_STUDENTS"] / room_sum["ROOM_CAPACITY"]
        room_sum = room_sum.sort_values(
            ["DATE_ONLY", "TIME", "CAMPUS", "UTILIZATION"],
            ascending=[True, True, True, False],
        )
    else:
        room_sum = pd.DataFrame(
            columns=[
                "DATE_ONLY", "TIME", "CAMPUS", "ROOM ID",
                "ROOM_CAPACITY", "ROOM_EXAM_CAPACITY",
                "TOTAL_STUDENTS", "NUM_MODULES", "UTILIZATION",
            ]
        )

    room_sum.to_csv(OUT_ROOM_SUMMARY, index=False, encoding="utf-8-sig")

    unassigned_out = pd.DataFrame(all_unassigned)
    unassigned_out.to_csv(OUT_UNASSIGNED, index=False, encoding="utf-8-sig")

    if not alloc_out.empty:
        rooms_used_day = (
            alloc_out[["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID"]]
            .drop_duplicates()
            .groupby(["DATE_ONLY", "CAMPUS"], as_index=False)
            .size()
            .rename(columns={"size": "ROOM_SLOTS_USED"})
        )

        rooms_used_pivot = (
            rooms_used_day.pivot_table(
                index="DATE_ONLY",
                columns="CAMPUS",
                values="ROOM_SLOTS_USED",
                fill_value=0,
            )
            .reset_index()
        )

        for col in CAMPUSES:
            if col not in rooms_used_pivot.columns:
                rooms_used_pivot[col] = 0

        rooms_used_pivot["TOTAL_ROOM_SLOTS_USED"] = rooms_used_pivot["CS1"] + rooms_used_pivot["CS2"]
        rooms_used_pivot = rooms_used_pivot.sort_values("DATE_ONLY")
    else:
        rooms_used_pivot = pd.DataFrame(columns=["DATE_ONLY", "CS1", "CS2", "TOTAL_ROOM_SLOTS_USED"])

    rooms_used_pivot.to_csv(OUT_ROOMS_USED_PER_DAY, index=False, encoding="utf-8-sig")

    df_tongket = build_overall_summary(
        students_df=students_df,
        alloc_out=alloc_out,
        unassigned_out=unassigned_out,
        rooms_df=rooms_df,
        rooms_used_pivot=rooms_used_pivot,
    )
    df_tongket.to_csv(OUT_TONGKET, index=False, encoding="utf-8-sig")

    print("Created:")
    print(f" - {OUT_ALLOC}")
    print(f" - {OUT_ROOM_SUMMARY}")
    print(f" - {OUT_UNASSIGNED}")
    print(f" - {OUT_ROOMS_USED_PER_DAY}")
    print(f" - {OUT_TONGKET}")

    print("\n=== OVERALL SUMMARY ===")
    print(df_tongket.to_string(index=False))


if __name__ == "__main__":
    main()
