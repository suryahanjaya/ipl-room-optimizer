import argparse
from pathlib import Path
from collections import defaultdict
import time

import pandas as pd


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


class Bin:
    __slots__ = ("host", "capacity", "used", "subjects", "members")

    def __init__(self, host: int, capacity: int, used: int, subject: str):
        self.host = host
        self.capacity = int(capacity)
        self.used = int(used)
        self.subjects = {subject}
        self.members = [host]

    @property
    def remaining(self) -> int:
        return self.capacity - self.used


def _best_fit_bin(item_subj: str, item_size: int, bins):
    """Best-Fit: chọn bin có remaining sau khi đặt là nhỏ nhất nhưng không âm, và không trùng môn."""
    best = None
    best_rem_after = None
    for b in bins:
        if item_subj in b.subjects:
            continue
        rem_after = b.remaining - item_size
        if rem_after < 0:
            continue
        if best is None or rem_after < best_rem_after:
            best = b
            best_rem_after = rem_after
    return best


def greedy_pack_with_conflict(rooms, subjects, students, caps):
    """
    Greedy Heuristic:
    - Best-Fit Decreasing (theo students giảm dần)
    - Mỗi item: nhét vào bin hợp lệ tốt nhất, nếu không có thì mở bin mới tại chính item đó
    - Post-process: thử đóng bớt bin bằng cách chuyển hết members sang bin khác (nếu được)
    """
    n = len(rooms)
    idxs = list(range(n))
    idxs.sort(key=lambda i: (students[i], caps[i]), reverse=True)

    assign = [-1] * n
    bins = []

    # (1) initial packing
    for i in idxs:
        s = subjects[i]
        size = int(students[i])
        b = _best_fit_bin(s, size, bins)
        if b is None:
            b = Bin(host=i, capacity=caps[i], used=size, subject=s)
            bins.append(b)
            assign[i] = i
        else:
            b.used += size
            b.subjects.add(s)
            b.members.append(i)
            assign[i] = b.host

    host_to_bin = {b.host: b for b in bins}

    # (2) local improvement: try to close bins (small/easy bins first)
    improved = True
    passes = 0
    while improved and passes < 5:
        passes += 1
        improved = False

        bins = list(host_to_bin.values())
        bins.sort(key=lambda b: (len(b.members), b.used))

        for b in list(bins):
            if len(host_to_bin) <= 1:
                break

            other_bins = [ob for ob in host_to_bin.values() if ob.host != b.host]
            items = list(b.members)
            items.sort(key=lambda i: students[i], reverse=True)

            # snapshot for rollback
            snapshot = [(ob.host, ob.used, set(ob.subjects), list(ob.members)) for ob in other_bins]

            move_plan = {}
            ok = True
            for i in items:
                s_i = subjects[i]
                size_i = int(students[i])
                ob = _best_fit_bin(s_i, size_i, other_bins)
                if ob is None:
                    ok = False
                    break
                ob.used += size_i
                ob.subjects.add(s_i)
                ob.members.append(i)
                move_plan[i] = ob.host

            if not ok:
                # rollback
                for (host, used, subjs, mems) in snapshot:
                    ob = host_to_bin[host]
                    ob.used = used
                    ob.subjects = subjs
                    ob.members = mems
                continue

            # success: close bin b
            for i, new_host in move_plan.items():
                assign[i] = new_host

            del host_to_bin[b.host]
            improved = True
            break

    open_idx = sorted(list(host_to_bin.keys()), key=lambda t: rooms[t])
    info = {
        "objective": float(len(open_idx)),
        "status": "Heuristic_Greedy_BFD",
        "passes": passes,
        "bins_open": len(open_idx),
    }
    return assign, open_idx, info


def build_outputs(assign, open_idx, shift, campus, rooms, subjects, students, caps):
    """Giữ schema output giống merging.py"""
    members = {j: [] for j in open_idx}
    for i, j in enumerate(assign):
        if j not in members:
            j = i
            assign[i] = j
            if j not in members:
                members[j] = []
                open_idx.append(j)
        members[j].append(i)

    groups, merges, merged_rooms = [], [], []

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
        description="Greedy Heuristic: gộp phòng cùng ca + cùng cơ sở + khác môn + đủ sức chứa. Xuất 2 file giống merging.py."
    )
    parser.add_argument("-i", "--input", required=True, help="Excel input (.xlsx)")
    parser.add_argument("-o", "--output", default="IPL_merge_result_greedy.xlsx", help="Main output Excel")
    parser.add_argument("--merged-out", default="phong_sau_gop_greedy.xlsx", help="Merged rooms Excel")
    parser.add_argument("-s", "--sheet", default=0, help="Sheet name or index (default 0)")
    parser.add_argument("--verbose", action="store_true", help="In runtime per group")
    args = parser.parse_args()

    t_all0 = time.perf_counter()
    df = pd.read_excel(args.input, sheet_name=args.sheet)

    col_room = pick_col(df, ["Phòng", "Phong", "Room", "Mã phòng", "Ma phong"])
    col_shift = pick_col(df, ["Ca thi", "Ca", "Cathi", "Shift", "Ca_thi"])
    col_subj = pick_col(df, ["Mã môn", "Ma mon", "Mon thi", "Môn thi", "Subject", "Ma_mon"])
    col_students = pick_col(df, ["Số sinh viên tham gia thi", "So SV", "So thi sinh", "Students", "Thi sinh"])
    col_capacity = pick_col(df, ["Sức chứa thi", "Suc chua", "Capacity", "So cho", "Sức chứa"])
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
        n = len(g)

        t0 = time.perf_counter()
        assign, open_idx, info = greedy_pack_with_conflict(rooms, subjects, students, caps)
        t1 = time.perf_counter()

        groups, merges, merged_rooms = build_outputs(assign, open_idx, shift, campus, rooms, subjects, students, caps)

        groups_all.extend(groups)
        merges_all.extend(merges)
        merged_all.extend(merged_rooms)

        stats_rows.append({
            "shift": shift,
            "campus": campus,
            "n_rooms_in_group": n,
            "bins_open": int(info.get("bins_open", len(open_idx))),
            "objective": float(info.get("objective", len(open_idx))),
            "passes": int(info.get("passes", 0)),
            "runtime_sec": round(t1 - t0, 4),
            "status": info.get("status", "Heuristic"),
        })

        summary_rows.append({
            "shift": shift,
            "campus": campus,
            "rooms_before": n,
            "rooms_after": len(open_idx),
            "reduction": n - len(open_idx),
        })

        if args.verbose:
            print(f"[GROUP] shift={shift} campus={campus} n={n} after={len(open_idx)} time={t1-t0:.2f}s")

    summary_df = pd.DataFrame(summary_rows)
    groups_df = pd.DataFrame(groups_all)
    merges_df = pd.DataFrame(merges_all)
    merged_df = pd.DataFrame(merged_all)
    stats_df = pd.DataFrame(stats_rows)

    summary_by_shift = (summary_df
                        .groupby("shift", as_index=False)[["rooms_before", "rooms_after", "reduction"]]
                        .sum()
                        .sort_values("shift"))

    summary_by_group = (summary_df
                        .groupby(["shift", "campus"], as_index=False)[["rooms_before", "rooms_after", "reduction"]]
                        .sum()
                        .sort_values(["shift", "campus"]))

    out_main = Path(args.output)
    out_merged = Path(args.merged_out)

    with pd.ExcelWriter(out_main, engine="openpyxl") as w:
        summary_by_shift.to_excel(w, sheet_name="Summary", index=False)
        summary_by_group.to_excel(w, sheet_name="Summary_ByCampus", index=False)
        groups_df.to_excel(w, sheet_name="Groups", index=False)
        merges_df.to_excel(w, sheet_name="Merges", index=False)
        stats_df.to_excel(w, sheet_name="HEUR_Stats", index=False)

    with pd.ExcelWriter(out_merged, engine="openpyxl") as w:
        merged_df.to_excel(w, sheet_name="MergedRooms", index=False)

    t_all1 = time.perf_counter()
    print(f"✅ Done. Main output: {out_main} (total {t_all1 - t_all0:.2f}s)")
    print(f"✅ Done. MergedRooms output: {out_merged}")


if __name__ == "__main__":
    main()
