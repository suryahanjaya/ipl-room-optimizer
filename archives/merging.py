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

    # (1) assignment: sum_j x_ij = 1
    for i in range(n):
        prob += pulp.lpSum(x[(i, j)] for j in feasible_js[i]) == 1

    # (2) capacity: sum_i students_i x_ij <= cap_j y_j
    # Need list of i that can go to j
    feasible_is = defaultdict(list)
    for i, j in feasible:
        feasible_is[j].append(i)

    for j in range(n):
        prob += pulp.lpSum(students[i] * x[(i, j)] for i in feasible_is[j]) <= caps[j] * y[j]

    # (3) distinct subjects per destination room
    for j in range(n):
        for s, idxs in subj_to_items.items():
            terms = []
            for i in idxs:
                if (i, j) in x:
                    terms.append(x[(i, j)])
            if terms:
                prob += pulp.lpSum(terms) <= 1

    # (4) y_j == x_jj
    for j in range(n):
        prob += y[j] == x[(j, j)]

    # CUTS (HƯỚNG B) — viết đúng
    total_students = sum(students)
    prob += pulp.lpSum(caps[j] * y[j] for j in range(n)) >= total_students

    need = max((len(v) for v in subj_to_items.values()), default=0)
    prob += pulp.lpSum(y[j] for j in range(n)) >= need

    # solve
    solver = pulp.PULP_CBC_CMD(msg=False)  # msg=True nếu bạn muốn xem log
    status = prob.solve(solver)

    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"MILP failed: status={pulp.LpStatus[status]}")

    # extract
    open_idx = [j for j in range(n) if pulp.value(y[j]) > 0.5]

    assign = [-1] * n
    for i in range(n):
        chosen = None
        for j in feasible_js[i]:
            if pulp.value(x[(i, j)]) > 0.5:
                chosen = j
                break
        if chosen is None:
            raise RuntimeError("No assignment for some room (unexpected).")
        assign[i] = chosen

    return assign, open_idx, {
        "objective": pulp.value(prob.objective),
        "status": pulp.LpStatus[status],
    }


def build_outputs_for_group(shift, campus, rooms, subjects, students, caps, assign, open_idx):
    open_set = set(open_idx)
    members = {j: [] for j in open_idx}
    for i, j in enumerate(assign):
        members[j].append(i)

    groups = []
    merges = []
    merged_rooms = []

    for gid, j in enumerate(sorted(open_idx, key=lambda t: rooms[t]), start=1):
        mem = members[j]
        mem_sorted = sorted(mem, key=lambda i: (0 if i == j else 1, rooms[i]))

        subj_list = [subjects[i] for i in mem_sorted]
        subj_str = "/".join(subj_list)
        room_list = [rooms[i] for i in mem_sorted]

        total = int(sum(students[i] for i in mem_sorted))
        remaining = int(caps[j] - total)

        groups.append({
            "shift": shift,
            "campus": campus,
            "group_id": gid,
            "kept_room": rooms[j],
            "kept_subject": subjects[j],
            "members_count": len(mem_sorted),
            "members_rooms": ", ".join(room_list),
            "members_subjects": ", ".join(subj_list),
            "merged_subjects": subj_str,
            "merged_students_total": total,
            "remaining_empty": remaining,
        })

        merged_rooms.append({
            "Phòng": rooms[j],
            "Ca thi": shift,
            "Cơ sở": campus,
            "Mã môn": subj_str,
            "Số sinh viên tham gia thi": total,
        })

        for i in mem_sorted:
            if i == j:
                continue
            merges.append({
                "shift": shift,
                "campus": campus,
                "from_room": rooms[i],
                "from_subject": subjects[i],
                "to_room": rooms[j],
                "to_subject": subjects[j],
            })

    return groups, merges, merged_rooms


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

    df = pd.read_excel(args.input, sheet_name=sheet_name)

    col_room = pick_col(df, ["Phòng", "Phong", "Room", "Mã phòng", "Ma phong"])
    col_shift = pick_col(df, ["Ca thi", "Ca", "Cathi", "Shift", "Ca_thi"])
    col_subj = pick_col(df, ["Mã môn", "Ma mon", "Mon thi", "Môn thi", "Subject", "Ma_mon"])
    col_students = pick_col(df, ["Số sinh viên tham gia thi", "So sinh vien tham gia thi", "Số thí sinh", "Students", "Số SV", "So SV"])
    col_capacity = pick_col(df, ["Sức chứa thi", "Suc chua thi", "Sức chứa", "Suc chua", "Capacity"])
    col_campus = pick_col(df, ["Cơ sở", "Co so", "Campus", "Facility", "Site"])

    missing = [name for name, col in [
        ("Phòng", col_room),
        ("Ca thi", col_shift),
        ("Mã môn", col_subj),
        ("Số SV", col_students),
        ("Sức chứa", col_capacity),
    ] if col is None]
    if missing:
        raise ValueError(f"Thiếu cột bắt buộc: {missing}. Cột hiện có: {list(df.columns)}")

    cols = [col_room, col_shift, col_subj, col_students, col_capacity] + ([col_campus] if col_campus else [])
    work = df[cols].copy()

    rename_map = {
        col_room: "room",
        col_shift: "shift",
        col_subj: "subject",
        col_students: "students",
        col_capacity: "capacity",
    }
    if col_campus:
        rename_map[col_campus] = "campus"
    work = work.rename(columns=rename_map)

    work["room"] = work["room"].astype(str).str.strip()
    work["shift"] = work["shift"].astype(str).str.strip()
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
    groups_all, merges_all, merged_all = [], [], []
    stats_rows = []

    for (shift, campus), g in work.groupby(["shift", "campus"], sort=True):
        g = g.reset_index(drop=True)
        rooms = g["room"].tolist()
        subjects = g["subject"].tolist()
        students = g["students"].tolist()
        caps = g["capacity"].tolist()

        print(f"Solving shift={shift}, campus={campus}, n={len(g)}")

        try:
            assign, open_idx, info = solve_group_exact_milp_pulp(rooms, subjects, students, caps)
        except Exception as e:
            print(f"❌ FAIL at shift={shift}, campus={campus}: {e}")
            if args.debug_dump:
                dump_path = f"FAIL_shift_{shift}_campus_{campus}.xlsx"
                g.to_excel(dump_path, index=False)
                print(f"   ↳ dumped failing group to: {dump_path}")
            raise

        groups, merges, merged_rooms = build_outputs_for_group(
            shift, campus, rooms, subjects, students, caps, assign, open_idx
        )

        summary_rows.append({
            "Ca thi": shift,
            "Cơ sở": campus,
            "Số phòng ban đầu": len(rooms),
            "Số phòng lúc sau (tối ưu)": len(open_idx),
            "Giảm": len(rooms) - len(open_idx),
        })

        stats_rows.append({
            "Ca thi": shift,
            "Cơ sở": campus,
            "objective(min rooms)": float(info["objective"]),
            "status": info["status"],
        })

        groups_all.extend(groups)
        merges_all.extend(merges)
        merged_all.extend(merged_rooms)

    summary_by_group = pd.DataFrame(summary_rows).sort_values(["Ca thi", "Cơ sở"]).reset_index(drop=True)
    summary_by_shift = (
        summary_by_group.groupby("Ca thi")[["Số phòng ban đầu", "Số phòng lúc sau (tối ưu)", "Giảm"]]
        .sum()
        .reset_index()
        .sort_values("Ca thi")
    )

    groups_df = pd.DataFrame(groups_all).sort_values(["shift", "campus", "group_id"]).reset_index(drop=True)
    merges_df = pd.DataFrame(merges_all).sort_values(["shift", "campus", "to_room", "from_room"]).reset_index(drop=True)
    merged_df = pd.DataFrame(merged_all).sort_values(["Ca thi", "Cơ sở", "Phòng"]).reset_index(drop=True)
    stats_df = pd.DataFrame(stats_rows).sort_values(["Ca thi", "Cơ sở"]).reset_index(drop=True)

    out_main = Path(args.output)
    out_merged = Path(args.merged_out)

    with pd.ExcelWriter(out_main, engine="openpyxl") as w:
        summary_by_shift.to_excel(w, sheet_name="Summary", index=False)
        summary_by_group.to_excel(w, sheet_name="Summary_ByCampus", index=False)
        groups_df.to_excel(w, sheet_name="Groups", index=False)
        merges_df.to_excel(w, sheet_name="Merges", index=False)
        stats_df.to_excel(w, sheet_name="MILP_Stats", index=False)

    with pd.ExcelWriter(out_merged, engine="openpyxl") as w:
        merged_df.to_excel(w, sheet_name="MergedRooms", index=False)

    print(f"✅ Done. Main output: {out_main}")
    print(f"✅ Done. MergedRooms output: {out_merged}")


if __name__ == "__main__":
    main()
