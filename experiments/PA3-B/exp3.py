import pandas as pd
from typing import Dict, List, Any, Tuple

# =========================================================
# FIXED VERSION + OVERALL SUMMARY (tongket.csv)
# + THÊM 2 PHÒNG DUMMY AVAILABLE MỌI CA, ĐÚNG CAMPUS
# + ƯU TIÊN DÙNG DUMMY TRƯỚC
#
# DUMMY ROOMS:
#   - H6-GD @ CS2, EXAM CAPACITY = 250
#   - B5-GD @ CS1, EXAM CAPACITY = 130
#
# Cách "ưu tiên":
#   - đưa dummy rooms lên đầu danh sách rooms_sorted
#   - (vẫn giữ sort theo exam_cap cho các phòng còn lại)
# =========================================================

STUDENTS_FILE = "students_by_course_datetime_campus.csv"
ROOMS_FILE = "rooms_capacity_campus.csv"

OUT_ALLOC = "allocation_plan.csv"
OUT_ROOM_SUMMARY = "allocation_room_summary.csv"
OUT_UNASSIGNED = "allocation_unassigned.csv"
OUT_ROOMS_USED_PER_DAY = "rooms_used_per_day_summary.csv"
OUT_TONGKET = "tongket.csv"

DUMMY_ROOMS = [
    {"ROOM ID": "H6-GD", "EXAM CAPACITY": 250, "CAMPUS_NORM": "CS2"},
    {"ROOM ID": "B5-GD", "EXAM CAPACITY": 130, "CAMPUS_NORM": "CS1"},
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
    for col in ["COURSE ID", "DATE_ONLY", "TIME"]:
        if col not in df.columns:
            raise ValueError(f"Missing column '{col}' in {students_path}")

    for campus_col in ["CS1", "CS2"]:
        if campus_col not in df.columns:
            df[campus_col] = 0

    df["CS1"] = pd.to_numeric(df["CS1"], errors="coerce").fillna(0).astype(int)
    df["CS2"] = pd.to_numeric(df["CS2"], errors="coerce").fillna(0).astype(int)

    # normalize campus-like values if present elsewhere (DATE_ONLY/TIME kept as-is)
    return df


def load_rooms(rooms_path: str) -> pd.DataFrame:
    df = pd.read_csv(rooms_path, encoding="utf-8-sig")
    required = ["ROOM ID", "EXAM CAPACITY", "CAMPUS_NORM"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing column '{col}' in {rooms_path}")

    df["EXAM CAPACITY"] = pd.to_numeric(df["EXAM CAPACITY"], errors="coerce")
    df = df.dropna(subset=["EXAM CAPACITY"]).copy()
    df["EXAM CAPACITY"] = df["EXAM CAPACITY"].astype(int)

    if "CAPACITY" in df.columns:
        df["CAPACITY"] = pd.to_numeric(df["CAPACITY"], errors="coerce")

    df["CAMPUS_NORM"] = df["CAMPUS_NORM"].apply(norm_campus)

    # ---- Add / overwrite dummy rooms into the inventory (available for all slots) ----
    dummy_df = pd.DataFrame(DUMMY_ROOMS)
    dummy_df["CAMPUS_NORM"] = dummy_df["CAMPUS_NORM"].apply(norm_campus)
    dummy_df["EXAM CAPACITY"] = pd.to_numeric(dummy_df["EXAM CAPACITY"], errors="coerce").fillna(0).astype(int)

    # remove same ROOM ID if already exists then append dummy
    df = df[~df["ROOM ID"].astype(str).isin(dummy_df["ROOM ID"].astype(str))].copy()
    df = pd.concat([df, dummy_df], ignore_index=True)

    return df


def split_allocate_fill_rooms(
    demands: List[Dict[str, Any]],
    rooms: List[Dict[str, Any]],
    dummy_room_ids: List[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    demands: [{"course_id":..., "students":..., "date":..., "time":..., "campus":...}, ...]
    rooms:   [{"room_id":..., "exam_cap":...}, ...]
    dummy_room_ids: list of dummy rooms to prioritize

    Returns:
      allocations: chunk allocations (course can appear multiple times, split across rooms)
      unassigned: leftover demand not fitting due to insufficient total room capacity
    """
    remaining = {str(d["course_id"]): int(d["students"]) for d in demands}
    meta = {str(d["course_id"]): d for d in demands}

    def sorted_courses() -> List[str]:
        return sorted(
            [cid for cid, rem in remaining.items() if rem > 0],
            key=lambda cid: remaining[cid],
            reverse=True,
        )

    # ---- PRIORITIZE dummy rooms FIRST, then others by exam_cap desc ----
    dummy_set = set(str(x) for x in dummy_room_ids)

    dummy_rooms = [r for r in rooms if str(r["room_id"]) in dummy_set]
    other_rooms = [r for r in rooms if str(r["room_id"]) not in dummy_set]

    dummy_rooms = sorted(dummy_rooms, key=lambda r: int(r["exam_cap"]), reverse=True)
    other_rooms = sorted(other_rooms, key=lambda r: int(r["exam_cap"]), reverse=True)

    rooms_sorted = dummy_rooms + other_rooms

    allocations: List[Dict[str, Any]] = []

    for r in rooms_sorted:
        room_id = str(r["room_id"])
        room_exam_cap = int(r["exam_cap"])
        room_remaining_cap = room_exam_cap

        if room_remaining_cap <= 0:
            continue

        # Fill this room by allocating chunks from modules (largest remaining first)
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
                    "ROOM EXAM CAPACITY": room_exam_cap,
                    "COURSE ID": cid,
                    "ALLOCATED STUDENTS": int(chunk),
                }
            )

            remaining[cid] -= int(chunk)
            room_remaining_cap -= int(chunk)

    unassigned = []
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
                    "reason": "Not enough total room capacity in this slot/campus",
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
    # Demand totals
    demand_cs1 = int(students_df["CS1"].sum())
    demand_cs2 = int(students_df["CS2"].sum())
    demand_total = demand_cs1 + demand_cs2

    # Allocated totals
    allocated_total = int(alloc_out["ALLOCATED STUDENTS"].sum()) if not alloc_out.empty else 0
    allocated_cs1 = int(alloc_out.loc[alloc_out["CAMPUS"] == "CS1", "ALLOCATED STUDENTS"].sum()) if not alloc_out.empty else 0
    allocated_cs2 = int(alloc_out.loc[alloc_out["CAMPUS"] == "CS2", "ALLOCATED STUDENTS"].sum()) if not alloc_out.empty else 0

    # Unassigned totals
    unassigned_total = int(unassigned_out["UNASSIGNED STUDENTS"].sum()) if not unassigned_out.empty else 0
    unassigned_cs1 = int(unassigned_out.loc[unassigned_out["CAMPUS"] == "CS1", "UNASSIGNED STUDENTS"].sum()) if not unassigned_out.empty else 0
    unassigned_cs2 = int(unassigned_out.loc[unassigned_out["CAMPUS"] == "CS2", "UNASSIGNED STUDENTS"].sum()) if not unassigned_out.empty else 0

    # Coverage
    pct_allocated = (allocated_total / demand_total * 100) if demand_total else 0.0
    pct_unassigned = (unassigned_total / demand_total * 100) if demand_total else 0.0

    # Slot counts
    num_slots = int(students_df.groupby(["DATE_ONLY", "TIME"]).ngroups)

    # Room inventory
    rooms_inventory_cs1 = int((rooms_df["CAMPUS_NORM"] == "CS1").sum()) if "CAMPUS_NORM" in rooms_df.columns else 0
    rooms_inventory_cs2 = int((rooms_df["CAMPUS_NORM"] == "CS2").sum()) if "CAMPUS_NORM" in rooms_df.columns else 0
    rooms_inventory_total = rooms_inventory_cs1 + rooms_inventory_cs2

    # Rooms used totals (room-times): sum of TOTAL_ROOMS_USED_SUM over days
    if rooms_used_pivot is not None and not rooms_used_pivot.empty:
        total_room_times = int(rooms_used_pivot["TOTAL_ROOMS_USED_SUM"].sum()) if "TOTAL_ROOMS_USED_SUM" in rooms_used_pivot.columns else 0
        total_room_times_cs1 = int(rooms_used_pivot["CS1_SUM"].sum()) if "CS1_SUM" in rooms_used_pivot.columns else 0
        total_room_times_cs2 = int(rooms_used_pivot["CS2_SUM"].sum()) if "CS2_SUM" in rooms_used_pivot.columns else 0
        peak_concurrent = int(rooms_used_pivot["TOTAL_ROOMS_USED_PEAK"].max()) if "TOTAL_ROOMS_USED_PEAK" in rooms_used_pivot.columns else 0
    else:
        total_room_times = total_room_times_cs1 = total_room_times_cs2 = 0
        peak_concurrent = 0

    # Utilization (weighted by room capacities)
    if alloc_out is not None and not alloc_out.empty:
        room_sum = (
            alloc_out.groupby(["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID"], as_index=False)
            .agg(
                ROOM_EXAM_CAPACITY=("ROOM EXAM CAPACITY", "first"),
                TOTAL_STUDENTS=("ALLOCATED STUDENTS", "sum"),
            )
        )
        total_cap_used = int(room_sum["ROOM_EXAM_CAPACITY"].sum())
        total_students_in_used_rooms = int(room_sum["TOTAL_STUDENTS"].sum())
        weighted_util = (total_students_in_used_rooms / total_cap_used) if total_cap_used else 0.0
    else:
        weighted_util = 0.0
        total_cap_used = 0
        total_students_in_used_rooms = 0

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

        "ROOM_TIMES_USED_CS1_SUM": total_room_times_cs1,
        "ROOM_TIMES_USED_CS2_SUM": total_room_times_cs2,
        "ROOM_TIMES_USED_TOTAL_SUM": total_room_times,

        "PEAK_CONCURRENT_ROOMS_USED": peak_concurrent,

        "TOTAL_CAPACITY_USED_SUM": total_cap_used,
        "TOTAL_STUDENTS_IN_USED_ROOMS_SUM": total_students_in_used_rooms,
        "WEIGHTED_UTILIZATION_USED_ROOMS": round(float(weighted_util), 4),

        "DUMMY_ROOMS_ADDED": "H6-GD@CS2(250); B5-GD@CS1(130)",
        "DUMMY_PRIORITY": "YES (dummy rooms processed first)",
    }])


def main():
    students_df = load_students(STUDENTS_FILE)
    rooms_df = load_rooms(ROOMS_FILE)

    rooms_by_campus = {}
    for campus, g in rooms_df.groupby("CAMPUS_NORM"):
        rooms_by_campus[campus] = (
            g.sort_values("EXAM CAPACITY", ascending=False)[["ROOM ID", "EXAM CAPACITY"]]
            .to_dict("records")
        )

    all_allocations = []
    all_unassigned = []

    for (date_only, time_val), slot in students_df.groupby(["DATE_ONLY", "TIME"]):
        for campus in ["CS1", "CS2"]:
            if campus not in rooms_by_campus:
                continue

            demands = []
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

            rooms = [{"room_id": r["ROOM ID"], "exam_cap": int(r["EXAM CAPACITY"])} for r in rooms_by_campus[campus]]

            # dummy room ids for this campus only
            dummy_ids = [r["ROOM ID"] for r in DUMMY_ROOMS if norm_campus(r["CAMPUS_NORM"]) == campus]

            allocations, unassigned = split_allocate_fill_rooms(demands, rooms, dummy_room_ids=dummy_ids)
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
                ROOM_EXAM_CAPACITY=("ROOM EXAM CAPACITY", "first"),
                TOTAL_STUDENTS=("ALLOCATED STUDENTS", "sum"),
                NUM_MODULES=("COURSE ID", "nunique"),
            )
        )
        room_sum["UTILIZATION"] = room_sum["TOTAL_STUDENTS"] / room_sum["ROOM_EXAM_CAPACITY"]
        room_sum = room_sum.sort_values(
            ["DATE_ONLY", "TIME", "CAMPUS", "UTILIZATION"],
            ascending=[True, True, True, False]
        )
    else:
        room_sum = pd.DataFrame(
            columns=["DATE_ONLY", "TIME", "CAMPUS", "ROOM ID", "ROOM EXAM CAPACITY", "TOTAL_STUDENTS", "NUM_MODULES", "UTILIZATION"]
        )

    room_sum.to_csv(OUT_ROOM_SUMMARY, index=False, encoding="utf-8-sig")

    # ===== Unassigned =====
    unassigned_out = pd.DataFrame(all_unassigned)
    unassigned_out.to_csv(OUT_UNASSIGNED, index=False, encoding="utf-8-sig")

    # ===== Rooms used per day (CS1/CS2) =====
    if not alloc_out.empty:
        rooms_used_slot = (
            alloc_out.groupby(["DATE_ONLY", "TIME", "CAMPUS"])["ROOM ID"]
            .nunique()
            .reset_index(name="ROOMS_USED")
            .sort_values(["DATE_ONLY", "TIME", "CAMPUS"])
        )

        rooms_used_day_sum = (
            rooms_used_slot.groupby(["DATE_ONLY", "CAMPUS"], as_index=False)["ROOMS_USED"]
            .sum()
            .rename(columns={"ROOMS_USED": "ROOMS_USED_SUM"})
        )

        rooms_used_day_peak = (
            rooms_used_slot.groupby(["DATE_ONLY", "CAMPUS"], as_index=False)["ROOMS_USED"]
            .max()
            .rename(columns={"ROOMS_USED": "ROOMS_USED_PEAK"})
        )

        rooms_used_day = rooms_used_day_sum.merge(
            rooms_used_day_peak, on=["DATE_ONLY", "CAMPUS"], how="outer"
        )

        pivot_sum = (
            rooms_used_day.pivot_table(
                index="DATE_ONLY", columns="CAMPUS", values="ROOMS_USED_SUM", fill_value=0
            )
            .reset_index()
        )
        for col in ["CS1", "CS2"]:
            if col not in pivot_sum.columns:
                pivot_sum[col] = 0
        pivot_sum["TOTAL_ROOMS_USED_SUM"] = pivot_sum["CS1"] + pivot_sum["CS2"]
        pivot_sum = pivot_sum.sort_values("DATE_ONLY")

        pivot_peak = (
            rooms_used_day.pivot_table(
                index="DATE_ONLY", columns="CAMPUS", values="ROOMS_USED_PEAK", fill_value=0
            )
            .reset_index()
        )
        for col in ["CS1", "CS2"]:
            if col not in pivot_peak.columns:
                pivot_peak[col] = 0
        pivot_peak["TOTAL_ROOMS_USED_PEAK"] = pivot_peak["CS1"] + pivot_peak["CS2"]
        pivot_peak = pivot_peak.sort_values("DATE_ONLY")

        rooms_used_pivot = pivot_sum.merge(pivot_peak, on="DATE_ONLY", suffixes=("_SUM", "_PEAK"))

    else:
        rooms_used_pivot = pd.DataFrame(columns=[
            "DATE_ONLY",
            "CS1_SUM", "CS2_SUM", "TOTAL_ROOMS_USED_SUM",
            "CS1_PEAK", "CS2_PEAK", "TOTAL_ROOMS_USED_PEAK"
        ])

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
    print(f" - {OUT_ALLOC} (allocation with splitting allowed; dummy rooms prioritized)")
    print(f" - {OUT_ROOM_SUMMARY} (room utilization per slot)")
    print(f" - {OUT_UNASSIGNED} (leftover demand)")
    print(f" - {OUT_ROOMS_USED_PER_DAY} (rooms used per day in CS1/CS2)")
    print(f" - {OUT_TONGKET} (overall summary)")

    print("\n=== OVERALL SUMMARY ===")
    print(df_tongket.to_string(index=False))

    print("\nQuick stats:")
    print(f"Allocated rows: {len(alloc_out)}")
    print(f"Unassigned rows: {len(unassigned_out)}")

    if not unassigned_out.empty:
        print("\nTop 10 unassigned:")
        print(unassigned_out.head(10).to_string(index=False))

    if not rooms_used_pivot.empty:
        print("\nRooms used per day:")
        print(rooms_used_pivot.to_string(index=False))


if __name__ == "__main__":
    main()
