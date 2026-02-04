import pandas as pd
from typing import Dict, List, Any, Tuple

# =========================================================
# ROOM PACKING WITH TWO CAPACITIES + OVERALL SUMMARY (tongket.csv)
# + ADD 3 EXTRA ROOMS ALWAYS AVAILABLE:
#   - CS1: B5-GD (CAP=130, EXAM CAP=130)
#   - CS2: H6-GD (CAP=250, EXAM CAP=250)
#   - CS2: NTD   (CAP=300, EXAM CAP=300)
#
# Inputs:
#   1) students_by_course_datetime_campus.csv
#      Required columns: "COURSE ID", "DATE_ONLY", "TIME", "CS1", "CS2"
#   2) rooms_capacity_campus.csv
#      Required columns: "ROOM ID", "CAPACITY", "EXAM CAPACITY", "CAMPUS_NORM"
#      Optional: "CAMPUS_CONFLICT" (TRUE/FALSE) -> if TRUE, exclude that room
#
# Constraints (per (DATE_ONLY, TIME, CAMPUS)):
#   1) Total students in a room across all courses <= CAPACITY(room)
#   2) For each (COURSE, ROOM): assigned students <= EXAM CAPACITY(room)
#   3) Multiple courses can share a room
#   4) One course demand can be split across multiple rooms
#
# Heuristic (Greedy fill):
#   - Sort rooms by CAPACITY descending (fill big rooms first)
#   - For each room, iterate courses by remaining demand descending:
#       chunk = min(remaining_course, remaining_room_capacity, exam_capacity_per_course)
#
# Outputs:
#   - allocation_plan.csv
#   - allocation_room_summary.csv
#   - allocation_unassigned.csv
#   - rooms_used_per_day_summary.csv
#   - tongket.csv
# =========================================================

STUDENTS_FILE = "students_by_course_datetime_campus.csv"
ROOMS_FILE = "rooms_capacity_campus.csv"

OUT_ALLOC = "allocation_plan.csv"
OUT_ROOM_SUMMARY = "allocation_room_summary.csv"
OUT_UNASSIGNED = "allocation_unassigned.csv"
OUT_ROOMS_USED_PER_DAY = "rooms_used_per_day_summary.csv"
OUT_TONGKET = "tongket.csv"

CAMPUSES = ["CS1", "CS2"]

EXTRA_ROOMS = [
    {"ROOM ID": "B5-GD", "CAPACITY": 130, "EXAM CAPACITY": 130, "CAMPUS_NORM": "CS1"},
    {"ROOM ID": "H6-GD", "CAPACITY": 250, "EXAM CAPACITY": 250, "CAMPUS_NORM": "CS2"},
    {"ROOM ID": "NTD",   "CAPACITY": 300, "EXAM CAPACITY": 300, "CAMPUS_NORM": "CS2"},
]


def norm_campus(x: Any) -> str:
    s = str(x).strip().upper()
    if s == "1":
        return "CS1"
    if s == "2":
        return "CS2"
    return s


def load_students(students_path: str) -> pd.DataFrame:
    df = pd.read_csv(students_path, encoding="utf-8-sig")

    required = ["COURSE ID", "DATE_ONLY", "TIME"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in {students_path}: {missing}")

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
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in {rooms_path}: {missing}")

    # Optional: exclude conflict rooms
    if "CAMPUS_CONFLICT" in df.columns:
        df["CAMPUS_CONFLICT"] = df["CAMPUS_CONFLICT"].astype(str).str.upper().str.strip()
        df = df[df["CAMPUS_CONFLICT"] != "TRUE"].copy()

    df["ROOM ID"] = df["ROOM ID"].astype(str).str.strip()

    df["CAPACITY"] = pd.to_numeric(df["CAPACITY"], errors="coerce")
    df["EXAM CAPACITY"] = pd.to_numeric(df["EXAM CAPACITY"], errors="coerce")
    df = df.dropna(subset=["CAPACITY", "EXAM CAPACITY"]).copy()
    df["CAPACITY"] = df["CAPACITY"].astype(int)
    df["EXAM CAPACITY"] = df["EXAM CAPACITY"].astype(int)

    df["CAMPUS_NORM"] = df["CAMPUS_NORM"].apply(norm_campus)

    return df


def add_extra_rooms_always_available(rooms_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add always-available rooms (if not already present).
    If a ROOM ID already exists, do not duplicate and do not override.
    """
    rooms_df = rooms_df.copy()
    rooms_df["ROOM ID"] = rooms_df["ROOM ID"].astype(str).str.strip()
    rooms_df["CAMPUS_NORM"] = rooms_df["CAMPUS_NORM"].apply(norm_campus)

    extra_df = pd.DataFrame(EXTRA_ROOMS)
    extra_df["ROOM ID"] = extra_df["ROOM ID"].astype(str).str.strip()
    extra_df["CAMPUS_NORM"] = extra_df["CAMPUS_NORM"].apply(norm_campus)
    extra_df["CAPACITY"] = pd.to_numeric(extra_df["CAPACITY"], errors="coerce").fillna(0).astype(int)
    extra_df["EXAM CAPACITY"] = pd.to_numeric(extra_df["EXAM CAPACITY"], errors="coerce").fillna(0).astype(int)

    existing_ids = set(rooms_df["ROOM ID"].tolist())
    to_add = extra_df[~extra_df["ROOM ID"].isin(existing_ids)].copy()
    if not to_add.empty:
        rooms_df = pd.concat([rooms_df, to_add], ignore_index=True)

    return rooms_df


def split_allocate_fill_rooms(
    demands: List[Dict[str, Any]],
    rooms: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    demands: [{"course_id":..., "students":..., "date":..., "time":..., "campus":...}, ...]
    rooms:   [{"room_id":..., "cap":..., "exam_cap":...}, ...]

    Returns:
      allocations: chunk allocations; a course can appear in multiple rooms
      unassigned: remaining demand that couldn't fit
    """
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
        room_id = str(r["room_id"])
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
    # Total demand
    demand_cs1 = int(students_df["CS1"].sum())
    demand_cs2 = int(students_df["CS2"].sum())
    demand_total = demand_cs1 + demand_cs2

    # Total allocated
    allocated_total = int(alloc_out["ALLOCATED STUDENTS"].sum()) if not alloc_out.empty else 0
    allocated_cs1 = int(alloc_out.loc[alloc_out["CAMPUS"] == "CS1", "ALLOCATED STUDENTS"].sum()) if not alloc_out.empty else 0
    allocated_cs2 = int(alloc_out.loc[alloc_out["CAMPUS"] == "CS2", "ALLOCATED STUDENTS"].sum()) if not alloc_out.empty else 0

    # Total unassigned
    unassigned_total = int(unassigned_out["UNASSIGNED STUDENTS"].sum()) if not unassigned_out.empty else 0
    unassigned_cs1 = int(unassigned_out.loc[unassigned_out["CAMPUS"] == "CS1", "UNASSIGNED STUDENTS"].sum()) if not unassigned_out.empty else 0
    unassigned_cs2 = int(unassigned_out.loc[unassigned_out["CAMPUS"] == "CS2", "UNASSIGNED STUDENTS"].sum()) if not unassigned_out.empty else 0

    pct_allocated = (allocated_total / demand_total * 100) if demand_total else 0.0
    pct_unassigned = (unassigned_total / demand_total * 100) if demand_total else 0.0

    # How many time slots (DATE_ONLY, TIME)
    num_slots = int(students_df.groupby(["DATE_ONLY", "TIME"]).ngroups)

    # Rooms inventory (post-filter + extra rooms)
    rooms_inventory_cs1 = int((rooms_df["CAMPUS_NORM"] == "CS1").sum()) if "CAMPUS_NORM" in rooms_df.columns else 0
    rooms_inventory_cs2 = int((rooms_df["CAMPUS_NORM"] == "CS2").sum()) if "CAMPUS_NORM" in rooms_df.columns else 0
    rooms_inventory_total = rooms_inventory_cs1 + rooms_inventory_cs2

    # Rooms used (room-slots) totals
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

    # Weighted utilization over USED room-slots (based on ROOM CAPACITY)
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

        "EXTRA_ROOMS_ALWAYS_AVAILABLE": "CS1:B5-GD(130/130); CS2:H6-GD(250/250); CS2:NTD(300/300)",
    }])


def main():
    students_df = load_students(STUDENTS_FILE)
    rooms_df = load_rooms(ROOMS_FILE)

    # Add extra rooms
    rooms_df = add_extra_rooms_always_available(rooms_df)

    # Rooms grouped by campus, sorted by CAPACITY (big rooms first)
    rooms_by_campus: Dict[str, List[Dict[str, Any]]] = {}
    for campus, g in rooms_df.groupby("CAMPUS_NORM"):
        rooms_by_campus[campus] = (
            g.sort_values("CAPACITY", ascending=False)[["ROOM ID", "CAPACITY", "EXAM CAPACITY"]]
            .to_dict("records")
        )

    all_allocations: List[Dict[str, Any]] = []
    all_unassigned: List[Dict[str, Any]] = []

    # Allocate per (DATE_ONLY, TIME, CAMPUS)
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
                {
                    "room_id": str(r["ROOM ID"]),
                    "cap": int(r["CAPACITY"]),
                    "exam_cap": int(r["EXAM CAPACITY"]),
                }
                for r in rooms_by_campus[campus]
            ]

            allocations, unassigned = split_allocate_fill_rooms(demands, rooms)
            all_allocations.extend(allocations)
            all_unassigned.extend(unassigned)

    # ===== Export allocation plan =====
    alloc_out = pd.DataFrame(all_allocations)
    if not alloc_out.empty:
        alloc_out = alloc_out.sort_values(["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID", "COURSE ID"])
    alloc_out.to_csv(OUT_ALLOC, index=False, encoding="utf-8-sig")

    # ===== Room summary per slot =====
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

    # ===== Unassigned =====
    unassigned_out = pd.DataFrame(all_unassigned)
    unassigned_out.to_csv(OUT_UNASSIGNED, index=False, encoding="utf-8-sig")

    # ===== Rooms used per day (CS1/CS2): count room-slots =====
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

    # ===== Overall summary (tongket.csv) =====
    df_tongket = build_overall_summary(
        students_df=students_df,
        alloc_out=alloc_out,
        unassigned_out=unassigned_out,
        rooms_df=rooms_df,
        rooms_used_pivot=rooms_used_pivot,
    )
    df_tongket.to_csv(OUT_TONGKET, index=False, encoding="utf-8-sig")

    # ===== Print summary =====
    print("Created:")
    print(f" - {OUT_ALLOC} (allocation with splitting allowed)")
    print(f" - {OUT_ROOM_SUMMARY} (room utilization per slot)")
    print(f" - {OUT_UNASSIGNED} (leftover demand)")
    print(f" - {OUT_ROOMS_USED_PER_DAY} (rooms used per day in CS1/CS2)")
    print(f" - {OUT_TONGKET} (overall summary)")

    print("\n=== OVERALL SUMMARY ===")
    print(df_tongket.to_string(index=False))

    if not unassigned_out.empty:
        print("\nTop 10 unassigned:")
        print(unassigned_out.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
