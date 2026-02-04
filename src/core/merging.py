import argparse
from pathlib import Path
from collections import defaultdict

import pandas as pd
import pulp


def pick_col(df: pd.DataFrame, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    cols = {str(col).strip().lower(): col for col in df.columns}
    for c in candidates:
        key = str(c).strip().lower()
        if key in cols:
            return cols[key]
    return None



def solve_group_greedy(rooms, subjects, students, caps):
    """
    Fast Greedy Heuristic (Best-Fit Decreasing) for large datasets.
    Sorts source rooms by size (ascending) and tries to fit them into the best available target room.
    Best fit = target with minimum remaining space after merge.
    """
    n = len(rooms)
    
    # Sanity check
    for i in range(n):
        if students[i] > caps[i]:
            raise ValueError(f"Dữ liệu lỗi: phòng {rooms[i]} có students={students[i]} > capacity={caps[i]}")

    assign = list(range(n))  # Initially everyone assigned to self
    current_load = list(students) # Track load in each room
    # Track sets of subjects in each room to ensure disjoint constraint
    current_subjects = [set([subjects[i]]) for i in range(n)]
    
    # Sort indices by number of students (Ascending)
    # Logic: Easier to squeeze small classes into gaps than large ones.
    sorted_indices = sorted(range(n), key=lambda i: students[i])
    
    for i in sorted_indices:
        # Simplified Greedy:
        # Try to move 'i' into some 'j' where 'j' is keeping itself.
        if assign[i] != i:
            continue # Already moved i somewhere
            
        best_j = -1
        min_waste = float('inf')
        
        # Candidates: j != i, and j must be a root (assign[j] == j)
        candidates = [j for j in range(n) if assign[j] == j and j != i]
        
        for j in candidates:
            # Capacity Check
            if current_load[j] + current_load[i] <= caps[j]:
                # Subject Check (must differ)
                if current_subjects[i].isdisjoint(current_subjects[j]):
                    # Score: Minimize waste (Best Fit)
                    waste = caps[j] - (current_load[j] + current_load[i])
                    if waste < min_waste:
                        min_waste = waste
                        best_j = j
        
        if best_j != -1:
            # Execute Merge
            assign[i] = best_j
            current_load[best_j] += current_load[i]
            current_subjects[best_j].update(current_subjects[i])
            # i is now effectively closed
            
    open_idx = [j for j in range(n) if assign[j] == j]
    
    return assign, open_idx, {
        "objective": len(open_idx),
        "status": "Heuristic_BestFit"
    }

def solve_group_exact_milp_pulp(rooms, subjects, students, caps):
    """
    Exact MILP solved by CBC (PuLP) = Branch-and-Bound + LP relaxation.

    Variables:
      y_j ∈ {0,1}: room j open after merge
      x_ij ∈ {0,1}: room i assigned to open room j

    Rules:
      - Always allow stay: x_ii exists
      - i -> j (i != j) allowed only if:
            subjects[i] != subjects[j]
            students[i] <= caps[j] - students[j]    (fits into empty seats of j)
      - Distinct subjects in each open room
      - y_j == x_jj (open iff keep itself)

    Objective:
      min sum_j y_j
    """
    n = len(rooms)

    # Hard sanity: each room must fit itself
    for i in range(n):
        if students[i] > caps[i]:
            raise ValueError(
                f"Dữ liệu lỗi: phòng {rooms[i]} có students={students[i]} > capacity={caps[i]}"
            )

    # feasible edges (i,j)
    feasible = []
    for i in range(n):
        for j in range(n):
            if i == j:
                feasible.append((i, j))
            else:
                if subjects[i] == subjects[j]:
                    continue
                empty_j = caps[j] - students[j]
                if students[i] <= empty_j:
                    feasible.append((i, j))

    # quick: every i must have at least one feasible destination (diagonal ensures it)
    feasible_js = defaultdict(list)
    for i, j in feasible:
        feasible_js[i].append(j)
    for i in range(n):
        if i not in feasible_js or len(feasible_js[i]) == 0:
            raise ValueError(f"Phòng {rooms[i]} không có đích hợp lệ nào (kể cả ở lại).")

    # subject index
    subj_to_items = defaultdict(list)
    for i, s in enumerate(subjects):
        subj_to_items[s].append(i)

    # model
    prob = pulp.LpProblem("RoomMerging", pulp.LpMinimize)

    y = pulp.LpVariable.dicts("y", list(range(n)), lowBound=0, upBound=1, cat=pulp.LpBinary)
    x = pulp.LpVariable.dicts("x", feasible, lowBound=0, upBound=1, cat=pulp.LpBinary)

    # objective
    prob += pulp.lpSum(y[j] for j in range(n))

    # (C1) assignment: sum_j x_ij = 1
    for i in range(n):
        prob += pulp.lpSum(x[(i, j)] for j in feasible_js[i]) == 1

    # (C2) xij <= yj (only assign to open rooms)
    for i in range(n):
        for j in feasible_js[i]:
            prob += x[(i, j)] <= y[j]

    # (C4) capacity: sum_i students_i x_ij <= cap_j y_j
    # Need list of i that can go to j
    feasible_is = defaultdict(list)
    for i, j in feasible:
        feasible_is[j].append(i)

    for j in range(n):
        prob += pulp.lpSum(students[i] * x[(i, j)] for i in feasible_is[j]) <= caps[j] * y[j]

    # (ADDITIONAL) distinct subjects per destination room
    for j in range(n):
        for s, idxs in subj_to_items.items():
            terms = []
            for i in idxs:
                if (i, j) in x:
                    terms.append(x[(i, j)])
            if terms:
                prob += pulp.lpSum(terms) <= 1

    # (C3) y_j == x_jj (room open iff it keeps itself)
    for j in range(n):
        prob += y[j] == x[(j, j)]

    # CUTS (HƯỚNG B) — viết đúng
    total_students = sum(students)
    prob += pulp.lpSum(caps[j] * y[j] for j in range(n)) >= total_students

    need = max((len(v) for v in subj_to_items.values()), default=0)
    prob += pulp.lpSum(y[j] for j in range(n)) >= need

    # solve
    # Add time limit to prevent hanging on large datasets (30 seconds per group)
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=30)  
    status = prob.solve(solver)

    if pulp.LpStatus[status] not in ["Optimal", "Feasible"]:
        # If time limit reached, it might return Not Solved but have values?
        # Usually CBC returns integer feasible if found.
        # Check if we have values
        if pulp.value(y[0]) is None:
             raise RuntimeError(f"MILP failed: status={pulp.LpStatus[status]}")
        print(f"[WARN] MILP not optimal ({pulp.LpStatus[status]}), using best found.")

    # extract
    open_idx = [j for j in range(n) if pulp.value(y[j]) > 0.5]

    assign = [-1] * n
    for i in range(n):
        chosen = None
        for j in feasible_js[i]:
            val = pulp.value(x[(i, j)])
            if val is not None and val > 0.5:
                chosen = j
                break
        if chosen is None:
            # Fallback: stay in own room if solver failed to assign
            # This handles cases where solver timed out or returned invalid state
            print(f"[WARN] Room {i} ({rooms[i]}) - no assignment found. Forcing stay.")
            chosen = i
            
        assign[i] = chosen

    # Re-derive open_idx from actual assignments to ensure consistency
    open_idx = sorted(list(set(assign)))

    return assign, open_idx, {
        "objective": pulp.value(prob.objective),
        "status": pulp.LpStatus[status],
    }


def build_outputs_for_group(shift, campus, rooms, subjects, students, caps, assign, open_idx):
    open_set = set(open_idx)
    members = defaultdict(list)
    for i, j in enumerate(assign):
        members[j].append(i)
        
    # Ensure all open rooms are keys in members, even if empty (unexpected but safe)
    for j in open_idx:
        if j not in members:
            members[j] = []

    groups = []
    merges = []
    merged_rooms = []
    room_changes = []

    # Track room changes
    all_rooms_set = set(range(len(rooms)))
    open_set_idx = set(open_idx)
    closed_rooms_idx = all_rooms_set - open_set_idx
    
    kept_rooms = [rooms[j] for j in open_idx]
    removed_rooms = [rooms[i] for i in closed_rooms_idx]

    for gid, j in enumerate(sorted(open_idx, key=lambda t: rooms[t]), start=1):
        mem = members[j]
        mem_sorted = sorted(mem, key=lambda i: (0 if i == j else 1, rooms[i]))

        subj_list = [subjects[i] for i in mem_sorted]
        subj_str = "/".join(subj_list)
        room_list = [rooms[i] for i in mem_sorted]

        total = int(sum(students[i] for i in mem_sorted))
        remaining = int(caps[j] - total)

        groups.append({
            "Shift": shift,
            "Campus": campus,
            "Group ID": gid,
            "Kept Room": rooms[j],
            "Kept Subject": subjects[j],
            "Members Count": len(mem_sorted),
            "Member Rooms": ", ".join(room_list),
            "Member Subjects": ", ".join(subj_list),
            "Merged Subjects": subj_str,
            "Total Students": total,
            "Remaining Capacity": remaining,
        })

        merged_rooms.append({
            "Room": rooms[j],
            "Shift": shift,
            "Campus": campus,
            "Subject Code": subj_str,
            "Number of Students": total,
        })

        for i in mem_sorted:
            if i == j:
                continue
            merges.append({
                "Shift": shift,
                "Campus": campus,
                "From Room": rooms[i],
                "From Subject": subjects[i],
                "From Students": students[i],
                "From Capacity": caps[i],
                "To Room": rooms[j],
                "To Subject": subjects[j],
            })

    # Create room change summary
    room_changes.append({
        "Shift": shift,
        "Campus": campus,
        "Initial Rooms Count": len(rooms),
        "Final Rooms Count": len(open_idx),
        "Rooms Removed Count": len(removed_rooms),
        "Kept Rooms": ", ".join(sorted(kept_rooms)),
        "Removed Rooms": ", ".join(sorted(removed_rooms)) if removed_rooms else "None",
    })

    return groups, merges, merged_rooms, room_changes


def main():
    parser = argparse.ArgumentParser(
        description="IPL Exact MILP (CBC): gộp phòng cùng ca + cùng cơ sở + khác môn + rule chỗ trống."
    )
    parser.add_argument("-i", "--input", required=True, help="Excel input (.xlsx)")
    parser.add_argument("-o", "--output", default="IPL_merge_result.xlsx", help="Main output Excel")
    parser.add_argument("--merged-out", default="phong_sau_gop.xlsx", help="Merged rooms Excel")
    parser.add_argument("-s", "--sheet", default=0, help="Sheet name or index (default 0)")
    parser.add_argument("--debug-dump", action="store_true", help="Dump failing group to xlsx if any error.")
    args = parser.parse_args()

    try:
        sheet_name = int(args.sheet)
    except ValueError:
        sheet_name = args.sheet

    if str(args.input).lower().endswith(".csv"):
        df = pd.read_csv(args.input)
    else:
        df = pd.read_excel(args.input, sheet_name=sheet_name)

    col_room = pick_col(df, ["Phòng", "Phong", "Room", "Mã phòng", "Ma phong", "F_TENPHMOI"])
    col_shift = pick_col(df, ["Ca thi", "Ca", "Cathi", "Shift", "Ca_thi", "GIOTHI_BD", "GI"])
    col_subj = pick_col(df, ["Mã môn", "Ma mon", "Mon thi", "Môn thi", "Subject", "Ma_mon", "F_MAMH"])
    col_students = pick_col(df, ["Số sinh viên tham gia thi", "So sinh vien tham gia thi", "Số thí sinh", "Students", "Số SV", "So SV", "F_SOLUONG"])
    col_capacity = pick_col(df, ["Sức chứa thi", "Suc chua thi", "Sức chứa", "Suc chua", "Capacity", "SUC_CHUA", "SUC_C"])
    col_campus = pick_col(df, ["Cơ sở", "Co so", "Campus", "Facility", "Site", "COSO"])
    col_date = pick_col(df, ["Ngay thi", "Ngày thi", "Date", "NGAYTHI", "Ngay"])

    missing = [name for name, col in [
        ("Phòng", col_room),
        ("Ca thi", col_shift),
        ("Mã môn", col_subj),
        ("Số SV", col_students),
        ("Sức chứa", col_capacity),
    ] if col is None]
    if missing:
        raise ValueError(f"Thiếu cột bắt buộc: {missing}. Cột hiện có: {list(df.columns)}")


    cols = [col_room, col_shift, col_subj, col_students, col_capacity]
    if col_campus:
        cols.append(col_campus)
    if col_date:
        cols.append(col_date)
        
    work = df[cols].copy()

    rename_map = {
        col_room: "room",
        col_shift: "raw_shift", # Rename original shift
        col_subj: "subject",
        col_students: "students",
        col_capacity: "capacity",
    }
    if col_campus:
        rename_map[col_campus] = "campus"
    if col_date:
        rename_map[col_date] = "date"
        
    work = work.rename(columns=rename_map)
    work["room"] = work["room"].astype(str).str.strip()
    work["raw_shift"] = work["raw_shift"].astype(str).str.strip()
    
    # Create composite shift ID if date exists
    if col_date and "date" in work.columns:
        work["date"] = work["date"].astype(str).str.strip()
        work["shift"] = work["date"] + "_" + work["raw_shift"]
    else:
        work["shift"] = work["raw_shift"]
    work["subject"] = work["subject"].astype(str).str.strip()

    work["students"] = pd.to_numeric(work["students"], errors="coerce")
    work["capacity"] = pd.to_numeric(work["capacity"], errors="coerce")
    if work[["students", "capacity"]].isna().any().any():
        bad = work[work[["students", "capacity"]].isna().any(axis=1)].head(20)
        raise ValueError("Có dòng students/capacity không phải số. Ví dụ:\n" + bad.to_string(index=False))

    work["students"] = work["students"].astype(int)
    work["capacity"] = work["capacity"].astype(int)

    if col_campus:
        work["campus"] = work["campus"].astype(str).str.strip()
    else:
        work["campus"] = "ALL"

    summary_rows = []
    groups_all, merges_all, merged_all, changes_all = [], [], [], []
    stats_rows = []

    for (shift, campus), g in work.groupby(["shift", "campus"], sort=True):
        g = g.reset_index(drop=True)
        rooms = g["room"].tolist()
        subjects = g["subject"].tolist()
        students = g["students"].tolist()
        caps = g["capacity"].tolist()

        print(f"Solving shift={shift}, campus={campus}, n={len(g)}")

        try:
            # Adaptive Solver Selection
            # For N > 80, Exact MILP is too slow/unstable. Switch to Greedy.
            if len(rooms) > 80:
                print(f"   [INFO] Large group (n={len(rooms)} > 80). Using Fast Heuristic...")
                assign, open_idx, info = solve_group_greedy(rooms, subjects, students, caps)
            else:
                try:
                    assign, open_idx, info = solve_group_exact_milp_pulp(rooms, subjects, students, caps)
                except Exception as e:
                    print(f"[WARN] MILP failed at shift={shift}, campus={campus}: {e}. Fallback to Greedy.")
                    assign, open_idx, info = solve_group_greedy(rooms, subjects, students, caps)
        except Exception as e:
            print(f"[ERROR] FAIL at shift={shift}, campus={campus}: {e}")
            if args.debug_dump:
                dump_path = f"FAIL_shift_{shift}_campus_{campus}.xlsx"
                g.to_excel(dump_path, index=False)
                print(f"   ↳ dumped failing group to: {dump_path}")
            raise

        groups, merges, merged_rooms, room_changes = build_outputs_for_group(
            shift, campus, rooms, subjects, students, caps, assign, open_idx
        )

        summary_rows.append({
            "Shift": shift,
            "Campus": campus,
            "Initial Rooms": len(rooms),
            "Final Rooms (Optimized)": len(open_idx),
            "Rooms Reduced": len(rooms) - len(open_idx),
        })

        stats_rows.append({
            "Shift": shift,
            "Campus": campus,
            "Objective (Min Rooms)": float(info["objective"]),
            "Status": info["status"],
        })

        groups_all.extend(groups)
        merges_all.extend(merges)
        merged_all.extend(merged_rooms)
        changes_all.extend(room_changes)

    summary_by_group = pd.DataFrame(summary_rows).sort_values(["Shift", "Campus"]).reset_index(drop=True)
    summary_by_shift = (
        summary_by_group.groupby("Shift")[["Initial Rooms", "Final Rooms (Optimized)", "Rooms Reduced"]]
        .sum()
        .reset_index()
        .sort_values("Shift")
    )

    groups_df = pd.DataFrame(groups_all).sort_values(["Shift", "Campus", "Group ID"]).reset_index(drop=True)
    merges_df = pd.DataFrame(merges_all).sort_values(["Shift", "Campus", "To Room", "From Room"]).reset_index(drop=True)
    merged_df = pd.DataFrame(merged_all).sort_values(["Shift", "Campus", "Room"]).reset_index(drop=True)
    stats_df = pd.DataFrame(stats_rows).sort_values(["Shift", "Campus"]).reset_index(drop=True)
    changes_df = pd.DataFrame(changes_all).sort_values(["Shift", "Campus"]).reset_index(drop=True)

    out_main = Path(args.output)
    out_merged = Path(args.merged_out)

    with pd.ExcelWriter(out_main, engine="openpyxl") as w:
        summary_by_shift.to_excel(w, sheet_name="Summary", index=False)
        summary_by_group.to_excel(w, sheet_name="Summary_ByCampus", index=False)
        changes_df.to_excel(w, sheet_name="Room_Changes_Detail", index=False)
        groups_df.to_excel(w, sheet_name="Groups", index=False)
        merges_df.to_excel(w, sheet_name="Merges", index=False)
        stats_df.to_excel(w, sheet_name="MILP_Stats", index=False)

    with pd.ExcelWriter(out_merged, engine="openpyxl") as w:
        merged_df.to_excel(w, sheet_name="MergedRooms", index=False)

    print(f"[SUCCESS] Done. Main output: {out_main}")
    print(f"[SUCCESS] Done. MergedRooms output: {out_merged}")


if __name__ == "__main__":
    main()
