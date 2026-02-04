"""
IPL Room Merging Optimizer
===========================
Implementation based on IPL (4).pdf specification.
Combines exact MILP solver with fast heuristic for large-scale datasets.

Core Algorithm:
- Phase 1: LP Relaxation for lower bound estimation
- Phase 2: Branch-and-Bound search with constraint propagation
- Adaptive solver selection based on problem size
- Best-Fit Decreasing heuristic for large instances

Author: Le Minh Hieu
Date: 2026-02-03
"""

import argparse
import time
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple, Dict, Set, Any

import pandas as pd
import pulp


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def identify_column(dataframe: pd.DataFrame, candidates: List[str]) -> str:
    """
    Identify column name from a list of candidates.
    Supports case-insensitive matching.
    
    Args:
        dataframe: Input DataFrame
        candidates: List of possible column names
        
    Returns:
        Matched column name or None
    """
    # Direct match
    for candidate in candidates:
        if candidate in dataframe.columns:
            return candidate
    
    # Case-insensitive match
    column_map = {str(col).strip().lower(): col for col in dataframe.columns}
    for candidate in candidates:
        normalized_key = str(candidate).strip().lower()
        if normalized_key in column_map:
            return column_map[normalized_key]
    
    return None


def validate_room_data(rooms: List[str], students: List[int], capacities: List[int]) -> None:
    """
    Validate that each room can accommodate its own students.
    
    Args:
        rooms: List of room identifiers
        students: Number of students per room
        capacities: Capacity of each room
        
    Raises:
        ValueError: If any room has students > capacity
    """
    for idx, (room, student_count, capacity) in enumerate(zip(rooms, students, capacities)):
        if student_count > capacity:
            raise ValueError(
                f"Data validation error: Room '{room}' (index {idx}) has "
                f"{student_count} students but capacity is only {capacity}"
            )


# ============================================================================
# GREEDY HEURISTIC SOLVER 
# ============================================================================

class GreedyBinPacker:
    """
    Best-Fit Decreasing heuristic for room merging.
    Time complexity: O(n²) where n is number of rooms.
    Space complexity: O(n)
    """
    
    def __init__(self, rooms: List[str], subjects: List[str], 
                 students: List[int], capacities: List[int]):
        self.rooms = rooms
        self.subjects = subjects
        self.students = students
        self.capacities = capacities
        self.num_rooms = len(rooms)
        
    def solve(self) -> Tuple[List[int], List[int], Dict[str, Any]]:
        """
        Execute greedy bin packing algorithm.
        
        Returns:
            assignment: List mapping each room to its destination
            open_rooms: List of room indices that remain open
            metadata: Solver statistics
        """
        validate_room_data(self.rooms, self.students, self.capacities)
        
        # Initialize: each room assigned to itself
        assignment = list(range(self.num_rooms))
        current_load = list(self.students)
        current_subjects = [set([subj]) for subj in self.subjects]
        
        # MULTI-PASS ALGORITHM: Try multiple strategies, pick the best
        # This strategy aims to maximize space utilization by evaluating multiple sorting criteria.
        
        def try_best_fit(order):
            """Try Best-Fit with given order"""
            assign = list(range(self.num_rooms))
            load = list(self.students)
            subj = [set([s]) for s in self.subjects]
            
            for src in order:
                if assign[src] != src:
                    continue
                best, min_w = None, float('inf')
                for tgt in range(self.num_rooms):
                    if assign[tgt] != tgt or tgt == src:
                        continue
                    total = load[tgt] + load[src]
                    if total > self.capacities[tgt]:
                        continue
                    if not subj[src].isdisjoint(subj[tgt]):
                        continue
                    w = self.capacities[tgt] - total
                    if w < min_w:
                        min_w, best = w, tgt
                if best is not None:
                    assign[src] = best
                    load[best] += load[src]
                    subj[best].update(subj[src])
            
            return assign, load, subj
        
        def try_first_fit(order):
            """Try First-Fit with given order"""
            assign = list(range(self.num_rooms))
            load = list(self.students)
            subj = [set([s]) for s in self.subjects]
            
            for src in order:
                if assign[src] != src:
                    continue
                for tgt in range(self.num_rooms):
                    if assign[tgt] != tgt or tgt == src:
                        continue
                    total = load[tgt] + load[src]
                    if total > self.capacities[tgt]:
                        continue
                    if not subj[src].isdisjoint(subj[tgt]):
                        continue
                    assign[src] = tgt
                    load[tgt] += load[src]
                    subj[tgt].update(subj[src])
                    break
            
            return assign, load, subj
        
        def try_worst_fit(order):
            """Try Worst-Fit with given order"""
            assign = list(range(self.num_rooms))
            load = list(self.students)
            subj = [set([s]) for s in self.subjects]
            
            for src in order:
                if assign[src] != src:
                    continue
                best, max_space = None, -1
                for tgt in range(self.num_rooms):
                    if assign[tgt] != tgt or tgt == src:
                        continue
                    total = load[tgt] + load[src]
                    if total > self.capacities[tgt]:
                        continue
                    if not subj[src].isdisjoint(subj[tgt]):
                        continue
                    space = self.capacities[tgt] - total
                    if space > max_space:
                        max_space, best = space, tgt
                if best is not None:
                    assign[src] = best
                    load[best] += load[src]
                    subj[best].update(subj[src])
            
            return assign, load, subj
        
        def count_open(assign):
            return sum(1 for i in range(self.num_rooms) if assign[i] == i)
        
        # Try all strategies
        order_asc = sorted(range(self.num_rooms), key=lambda i: self.students[i])
        order_desc = sorted(range(self.num_rooms), key=lambda i: self.students[i], reverse=True)
        order_cap = sorted(range(self.num_rooms), key=lambda i: self.capacities[i], reverse=True)
        
        results = [
            try_best_fit(order_asc),   # Strategy 1: BF-ASC
            try_best_fit(order_desc),  # Strategy 2: BF-DESC
            try_first_fit(order_desc), # Strategy 3: FF-DESC
            try_worst_fit(order_desc), # Strategy 4: WF-DESC
            try_best_fit(order_cap),   # Strategy 5: CAP-SORT
        ]
        
        # Find best result
        best_result = min(results, key=lambda x: count_open(x[0]))
        assignment, current_load, current_subjects = best_result
        
        open_rooms = [idx for idx in range(self.num_rooms) if assignment[idx] == idx]
        merge_count = self.num_rooms - len(open_rooms)
        
        return assignment, open_rooms, {
            "objective": len(open_rooms),
            "status": "Heuristic_MultiPass",
            "merges_performed": merge_count
        }


# ============================================================================
# Exact MILP Solver (for small-medium datasets)
# ============================================================================

class MILPRoomOptimizer:
    """
    Exact Integer Linear Programming solver using Branch-and-Bound.
    Implements IPL (4).pdf specification with LP relaxation.
    """
    
    def __init__(self, rooms: List[str], subjects: List[str],
                 students: List[int], capacities: List[int],
                 time_limit: int = 30):
        self.rooms = rooms
        self.subjects = subjects
        self.students = students
        self.capacities = capacities
        self.num_rooms = len(rooms)
        self.time_limit = time_limit
        
    def _build_feasible_edges(self) -> List[Tuple[int, int]]:
        """
        Construct feasible assignment edges (i, j).
        Edge (i, j) is feasible if:
        - i == j (room stays in itself), OR
        - subjects[i] != subjects[j] AND students[i] <= capacity[j] - students[j]
        
        Returns:
            List of feasible (source, destination) tuples
        """
        feasible = []
        
        for source in range(self.num_rooms):
            for dest in range(self.num_rooms):
                if source == dest:
                    # Self-assignment always feasible
                    feasible.append((source, dest))
                else:
                    # Check subject constraint
                    if self.subjects[source] == self.subjects[dest]:
                        continue
                    
                    # Check capacity constraint
                    available_space = self.capacities[dest] - self.students[dest]
                    if self.students[source] <= available_space:
                        feasible.append((source, dest))
        
        return feasible
    
    def _create_subject_index(self) -> Dict[str, List[int]]:
        """
        Create mapping from subject to list of room indices.
        
        Returns:
            Dictionary mapping subject code to room indices
        """
        subject_map = defaultdict(list)
        for idx, subject in enumerate(self.subjects):
            subject_map[subject].append(idx)
        return subject_map
    
    def solve(self) -> Tuple[List[int], List[int], Dict[str, Any]]:
        """
        Solve room merging problem using MILP with CBC solver.
        
        Returns:
            assignment: List mapping each room to its destination
            open_rooms: List of room indices that remain open
            metadata: Solver statistics
        """
        validate_room_data(self.rooms, self.students, self.capacities)
        
        # Build feasible edges
        feasible_edges = self._build_feasible_edges()
        
        # Create adjacency lists for efficient constraint generation
        outgoing_edges = defaultdict(list)  # source -> [destinations]
        incoming_edges = defaultdict(list)  # dest -> [sources]
        
        for source, dest in feasible_edges:
            outgoing_edges[source].append(dest)
            incoming_edges[dest].append(source)
        
        # Verify all rooms have at least self-assignment
        for idx in range(self.num_rooms):
            if idx not in outgoing_edges or len(outgoing_edges[idx]) == 0:
                raise ValueError(f"Room {self.rooms[idx]} has no feasible destination")
        
        # Create MILP model
        model = pulp.LpProblem("IPL_RoomMerging", pulp.LpMinimize)
        
        # Decision variables
        # y[j] = 1 if room j remains open
        y_vars = pulp.LpVariable.dicts(
            "open", 
            list(range(self.num_rooms)), 
            lowBound=0, upBound=1, cat=pulp.LpBinary
        )
        
        # x[(i,j)] = 1 if room i is assigned to room j
        x_vars = pulp.LpVariable.dicts(
            "assign", 
            feasible_edges, 
            lowBound=0, upBound=1, cat=pulp.LpBinary
        )
        
        # Objective: minimize number of open rooms
        model += pulp.lpSum(y_vars[j] for j in range(self.num_rooms))
        
        # Constraint C1: Each room assigned to exactly one destination
        for source in range(self.num_rooms):
            model += (
                pulp.lpSum(x_vars[(source, dest)] for dest in outgoing_edges[source]) == 1,
                f"Assignment_{source}"
            )
        
        # Constraint C2: Can only assign to open rooms
        for source in range(self.num_rooms):
            for dest in outgoing_edges[source]:
                model += (
                    x_vars[(source, dest)] <= y_vars[dest],
                    f"OpenRoom_{source}_{dest}"
                )
        
        # Constraint C3: Room is open iff it keeps itself
        for room_idx in range(self.num_rooms):
            model += (
                y_vars[room_idx] == x_vars[(room_idx, room_idx)],
                f"SelfAssign_{room_idx}"
            )
        
        # Constraint C4: Capacity constraint
        for dest in range(self.num_rooms):
            total_students = pulp.lpSum(
                self.students[source] * x_vars[(source, dest)]
                for source in incoming_edges[dest]
            )
            model += (
                total_students <= self.capacities[dest] * y_vars[dest],
                f"Capacity_{dest}"
            )
        
        # Additional constraint: Distinct subjects per destination room
        subject_index = self._create_subject_index()
        for dest in range(self.num_rooms):
            for subject, room_indices in subject_index.items():
                subject_assignments = []
                for source in room_indices:
                    if (source, dest) in x_vars:
                        subject_assignments.append(x_vars[(source, dest)])
                
                if subject_assignments:
                    model += (
                        pulp.lpSum(subject_assignments) <= 1,
                        f"SubjectDistinct_{dest}_{subject}"
                    )
        
        # Valid cuts for performance (from IPL 4.pdf)
        # Cut 1: Total capacity must accommodate all students
        total_students = sum(self.students)
        model += (
            pulp.lpSum(self.capacities[j] * y_vars[j] for j in range(self.num_rooms)) >= total_students,
            "ValidCut_TotalCapacity"
        )
        
        # Cut 2: Minimum rooms needed for subject diversity
        max_subject_count = max(len(indices) for indices in subject_index.values()) if subject_index else 0
        model += (
            pulp.lpSum(y_vars[j] for j in range(self.num_rooms)) >= max_subject_count,
            "ValidCut_SubjectDiversity"
        )
        
        # Solve using CBC solver with time limit
        solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=self.time_limit)
        status = model.solve(solver)
        
        # Extract solution
        status_name = pulp.LpStatus[status]
        
        if status_name not in ["Optimal", "Feasible"]:
            # Check if we have any solution
            if pulp.value(y_vars[0]) is None:
                raise RuntimeError(f"MILP solver failed with status: {status_name}")
            print(f"[WARNING] MILP not optimal ({status_name}), using best found solution")
        
        # Extract open rooms
        open_rooms = [j for j in range(self.num_rooms) if pulp.value(y_vars[j]) > 0.5]
        
        # Extract assignments
        assignment = [-1] * self.num_rooms
        for source in range(self.num_rooms):
            assigned_dest = None
            for dest in outgoing_edges[source]:
                if pulp.value(x_vars[(source, dest)]) > 0.5:
                    assigned_dest = dest
                    break
            
            if assigned_dest is None:
                # Fallback: assign to self
                print(f"[WARNING] Room {source} ({self.rooms[source]}) has no assignment, forcing self-assignment")
                assigned_dest = source
            
            assignment[source] = assigned_dest
        
        # Ensure consistency
        open_rooms = sorted(list(set(assignment)))
        
        return assignment, open_rooms, {
            "objective": pulp.value(model.objective) if pulp.value(model.objective) else len(open_rooms),
            "status": status_name
        }


# ============================================================================
# OUTPUT GENERATION
# ============================================================================

def generate_output_reports(shift: str, campus: str, 
                           rooms: List[str], subjects: List[str],
                           students: List[int], capacities: List[int],
                           assignment: List[int], open_rooms: List[int]) -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict]]:
    """
    Generate comprehensive output reports from solver results.
    
    Args:
        shift: Exam shift identifier
        campus: Campus identifier
        rooms: Room identifiers
        subjects: Subject codes
        students: Student counts
        capacities: Room capacities
        assignment: Assignment mapping
        open_rooms: List of open room indices
        
    Returns:
        Tuple of (groups, merges, merged_rooms, room_changes)
    """
    # Build membership mapping
    membership = defaultdict(list)
    for source_idx, dest_idx in enumerate(assignment):
        membership[dest_idx].append(source_idx)
    
    # Ensure all open rooms are in membership
    for room_idx in open_rooms:
        if room_idx not in membership:
            membership[room_idx] = []
    
    groups_data = []
    merges_data = []
    merged_rooms_data = []
    
    # Generate group reports
    for group_id, dest_idx in enumerate(sorted(open_rooms, key=lambda idx: rooms[idx]), start=1):
        members = membership[dest_idx]
        members_sorted = sorted(members, key=lambda idx: (0 if idx == dest_idx else 1, rooms[idx]))
        
        member_rooms = [rooms[idx] for idx in members_sorted]
        member_subjects = [subjects[idx] for idx in members_sorted]
        merged_subject_str = "/".join(member_subjects)
        
        total_students = sum(students[idx] for idx in members_sorted)
        remaining_capacity = capacities[dest_idx] - total_students
        
        groups_data.append({
            "Shift": shift,
            "Campus": campus,
            "Group ID": group_id,
            "Kept Room": rooms[dest_idx],
            "Kept Subject": subjects[dest_idx],
            "Members Count": len(members_sorted),
            "Member Rooms": ", ".join(member_rooms),
            "Member Subjects": ", ".join(member_subjects),
            "Merged Subjects": merged_subject_str,
            "Total Students": total_students,
            "Remaining Capacity": remaining_capacity,
        })
        
        merged_rooms_data.append({
            "Room": rooms[dest_idx],
            "Shift": shift,
            "Campus": campus,
            "Subject Code": merged_subject_str,
            "Number of Students": total_students,
        })
        
        # Record individual merges
        for source_idx in members_sorted:
            if source_idx == dest_idx:
                continue
            
            merges_data.append({
                "Shift": shift,
                "Campus": campus,
                "From Room": rooms[source_idx],
                "From Subject": subjects[source_idx],
                "From Students": students[source_idx],
                "From Capacity": capacities[source_idx],
                "To Room": rooms[dest_idx],
                "To Subject": subjects[dest_idx],
            })
    
    # Generate room change summary
    all_room_indices = set(range(len(rooms)))
    open_room_indices = set(open_rooms)
    closed_room_indices = all_room_indices - open_room_indices
    
    kept_room_names = sorted([rooms[idx] for idx in open_room_indices])
    removed_room_names = sorted([rooms[idx] for idx in closed_room_indices])
    
    room_changes_data = [{
        "Shift": shift,
        "Campus": campus,
        "Initial Rooms Count": len(rooms),
        "Final Rooms Count": len(open_rooms),
        "Rooms Removed Count": len(removed_room_names),
        "Kept Rooms": ", ".join(kept_room_names),
        "Removed Rooms": ", ".join(removed_room_names) if removed_room_names else "None",
    }]
    
    return groups_data, merges_data, merged_rooms_data, room_changes_data


# ============================================================================
# MAIN PROCESSING PIPELINE
# ============================================================================

def process_exam_data(
    input_path: Path,
    output_path: Path,
    sheet_name: str = 0,
    size_threshold: int = 15,
    time_limit: int = 300,
    verbose: bool = False
):
    """
    Main processing pipeline for exam room optimization.
    
    Args:
        input_path: Path to input Excel file
        output_path: Path for main output Excel file
        sheet_name: Sheet name or index to read
        size_threshold: Problem size threshold for solver selection
        time_limit: Time limit for MILP solver (seconds)
        verbose: Enable verbose logging
    """
    start_time = time.perf_counter()
    
    # Load data
    if input_path.lower().endswith('.csv'):
        dataframe = pd.read_csv(input_path)
    else:
        dataframe = pd.read_excel(input_path, sheet_name=sheet_name)
    
    # Identify columns (support multiple naming conventions)
    col_room = identify_column(dataframe, [
        "Phòng", "Room", "F_TENPHMOI", "ROOM ID", "ROOM_ID", "RoomID"
    ])
    col_shift = identify_column(dataframe, [
        "Ca thi", "Shift", "GIOTHI_BD", "GI", "TIME", "Time", "SHIFT", "KEY"
    ])
    col_subject = identify_column(dataframe, [
        "Mã môn", "Subject", "F_MAMH", "COURSE ID", "COURSE_ID", "CourseID", "Course"
    ])
    col_students = identify_column(dataframe, [
        "Số sinh viên tham gia thi", "Students", "F_SOLUONG", "STUDENTS", 
        "Student Count", "ALLOCATED STUDENTS", "Allocated Students"
    ])
    col_capacity = identify_column(dataframe, [
        "Sức chứa thi", "Capacity", "SUC_CHUA", "CAPACITY", "EXAM CAPACITY", 
        "Exam Capacity", "ROOM EXAM CAPACITY", "Room Exam Capacity"
    ])
    col_campus = identify_column(dataframe, [
        "Cơ sở", "Campus", "COSO", "CAMPUS"
    ])
    col_date = identify_column(dataframe, [
        "Ngày thi", "Date", "NGAYTHI", "DATE", "Exam Date", "DATE_ONLY"
    ])
    
    # Validate required columns
    required_columns = [
        ("Room", col_room),
        ("Shift", col_shift),
        ("Subject", col_subject),
        ("Students", col_students),
        ("Capacity", col_capacity),
    ]
    
    missing_columns = [name for name, col in required_columns if col is None]
    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}. "
            f"Available columns: {list(dataframe.columns)}"
        )
    
    # Select and rename columns
    selected_columns = [col_room, col_shift, col_subject, col_students, col_capacity]
    if col_campus:
        selected_columns.append(col_campus)
    if col_date:
        selected_columns.append(col_date)
    
    working_data = dataframe[selected_columns].copy()
    
    rename_mapping = {
        col_room: "room",
        col_shift: "raw_shift",
        col_subject: "subject",
        col_students: "students",
        col_capacity: "capacity",
    }
    if col_campus:
        rename_mapping[col_campus] = "campus"
    if col_date:
        rename_mapping[col_date] = "date"
    
    working_data = working_data.rename(columns=rename_mapping)
    
    # Data type conversions
    working_data["room"] = working_data["room"].astype(str).str.strip()
    working_data["raw_shift"] = working_data["raw_shift"].astype(str).str.strip()
    working_data["subject"] = working_data["subject"].astype(str).str.strip()
    
    # Create composite shift ID if date exists
    if col_date and "date" in working_data.columns:
        working_data["date"] = working_data["date"].astype(str).str.strip()
        working_data["shift"] = working_data["date"] + "_" + working_data["raw_shift"]
    else:
        working_data["shift"] = working_data["raw_shift"]
    
    # Convert numeric columns
    working_data["students"] = pd.to_numeric(working_data["students"], errors="coerce")
    working_data["capacity"] = pd.to_numeric(working_data["capacity"], errors="coerce")
    
    if working_data[["students", "capacity"]].isna().any().any():
        invalid_rows = working_data[working_data[["students", "capacity"]].isna().any(axis=1)].head(20)
        raise ValueError(
            "Found rows with non-numeric students/capacity values:\n" +
            invalid_rows.to_string(index=False)
        )
    
    working_data["students"] = working_data["students"].astype(int)
    working_data["capacity"] = working_data["capacity"].astype(int)
    
    # Handle campus column
    if col_campus:
        working_data["campus"] = working_data["campus"].astype(str).str.strip()
    else:
        working_data["campus"] = "ALL"
    
    # Initialize result collectors
    summary_records = []
    all_groups = []
    all_merges = []
    all_merged_rooms = []
    all_room_changes = []
    all_stats = []
    
    # Process each (shift, campus) group
    groups_to_process = list(working_data.groupby(["shift", "campus"], sort=True))
    total_groups = len(groups_to_process)
    print(f"Total Groups: {total_groups}")
    
    for i, ((shift_id, campus_id), group_data) in enumerate(groups_to_process, 1):
        group_data = group_data.reset_index(drop=True)
        
        rooms_list = group_data["room"].tolist()
        subjects_list = group_data["subject"].tolist()
        students_list = group_data["students"].tolist()
        capacities_list = group_data["capacity"].tolist()
        
        group_size = len(group_data)
        
        if verbose:
            print(f"Processing [{i}/{total_groups}]: shift={shift_id}, campus={campus_id}, rooms={group_size}")
        
        # Adaptive solver selection
        try:
            if group_size > size_threshold:
                if verbose:
                    print(f"  Using Greedy Heuristic (size {group_size} > {size_threshold})")
                
                solver = GreedyBinPacker(rooms_list, subjects_list, students_list, capacities_list)
                assignment, open_rooms, solver_info = solver.solve()
            else:
                try:
                    if verbose:
                        print(f"  Using Exact MILP (size {group_size} <= {size_threshold})")
                    
                    solver = MILPRoomOptimizer(
                        rooms_list, subjects_list, students_list, capacities_list,
                        time_limit=time_limit
                    )
                    assignment, open_rooms, solver_info = solver.solve()
                except Exception as milp_error:
                    print(f"[WARNING] MILP failed for shift={shift_id}, campus={campus_id}: {milp_error}")
                    print("  Falling back to Greedy Heuristic")
                    
                    solver = GreedyBinPacker(rooms_list, subjects_list, students_list, capacities_list)
                    assignment, open_rooms, solver_info = solver.solve()
        
        except Exception as error:
            print(f"[ERROR] Failed to process shift={shift_id}, campus={campus_id}: {error}")
            raise
        
        # Generate output reports
        groups, merges, merged_rooms, room_changes = generate_output_reports(
            shift_id, campus_id, rooms_list, subjects_list,
            students_list, capacities_list, assignment, open_rooms
        )
        
        all_groups.extend(groups)
        all_merges.extend(merges)
        all_merged_rooms.extend(merged_rooms)
        all_room_changes.extend(room_changes)
        
        summary_records.append({
            "Shift": shift_id,
            "Campus": campus_id,
            "Initial Rooms": group_size,
            "Final Rooms (Optimized)": len(open_rooms),
            "Rooms Reduced": group_size - len(open_rooms),
        })
        
        all_stats.append({
            "Shift": shift_id,
            "Campus": campus_id,
            "Objective (Min Rooms)": float(solver_info["objective"]),
            "Status": solver_info["status"],
        })
        
        if verbose:
            print(f"  Result: {group_size} -> {len(open_rooms)} rooms (saved {group_size - len(open_rooms)})")
    
    # Create summary DataFrames
    summary_by_group = pd.DataFrame(summary_records).sort_values(["Shift", "Campus"]).reset_index(drop=True)
    summary_by_shift = (
        summary_by_group.groupby("Shift")[["Initial Rooms", "Final Rooms (Optimized)", "Rooms Reduced"]]
        .sum()
        .reset_index()
        .sort_values("Shift")
    )
    
    groups_df = pd.DataFrame(all_groups).sort_values(["Shift", "Campus", "Group ID"]).reset_index(drop=True)
    merges_df = pd.DataFrame(all_merges).sort_values(["Shift", "Campus", "To Room", "From Room"]).reset_index(drop=True)
    stats_df = pd.DataFrame(all_stats).sort_values(["Shift", "Campus"]).reset_index(drop=True)
    changes_df = pd.DataFrame(all_room_changes).sort_values(["Shift", "Campus"]).reset_index(drop=True)
    
    # Write output files
    output_main = Path(output_path)
    
    # Ensure output directory exists
    output_main.parent.mkdir(parents=True, exist_ok=True)
    
    with pd.ExcelWriter(output_main, engine="openpyxl") as writer:
        summary_by_shift.to_excel(writer, sheet_name="Summary", index=False)
        summary_by_group.to_excel(writer, sheet_name="Summary_ByCampus", index=False)
        changes_df.to_excel(writer, sheet_name="Room_Changes_Detail", index=False)
        groups_df.to_excel(writer, sheet_name="Groups", index=False)
        merges_df.to_excel(writer, sheet_name="Merges", index=False)
        stats_df.to_excel(writer, sheet_name="MILP_Stats", index=False)
    
    elapsed_time = time.perf_counter() - start_time
    
    print(f"\n{'='*70}")
    print(f"SUCCESS: Processing completed in {elapsed_time:.2f} seconds")
    print(f"{'='*70}")
    print(f"Main output:   {output_main}")
    print(f"{'='*70}\n")


# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def main():
    """Command line interface for IPL room optimizer."""
    parser = argparse.ArgumentParser(
        description="IPL Room Merging Optimizer - Optimized implementation based on IPL (4).pdf",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ipl_optimizer.py -i data/input.xlsx -o results/output.xlsx
  python ipl_optimizer.py -i data/input.xlsx --verbose
  python ipl_optimizer.py -i data/input.xlsx --threshold 100 --time-limit 60
        """
    )
    
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Input Excel file path (.xlsx or .csv)"
    )
    
    parser.add_argument(
        "-o", "--output",
        default="IPL_merge_result.xlsx",
        help="Main output Excel file path (default: IPL_merge_result.xlsx)"
    )
    
    parser.add_argument(
        "--merged-out",
        default="phong_sau_gop.xlsx",
        help="Merged rooms output Excel file path (default: phong_sau_gop.xlsx)"
    )
    
    parser.add_argument(
        "-s", "--sheet",
        default=0,
        help="Sheet name or index to read (default: 0)"
    )
    
    parser.add_argument(
        "--threshold",
        type=int,
        default=80,
        help="Problem size threshold for solver selection (default: 80)"
    )
    
    parser.add_argument(
        "--time-limit",
        type=int,
        default=30,
        help="Time limit for MILP solver in seconds (default: 30)"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    # Convert sheet argument
    try:
        sheet_name = int(args.sheet)
    except ValueError:
        sheet_name = args.sheet
    
    # Execute processing
    process_exam_data(
        input_path=args.input,
        output_path=args.output,
        sheet_name=sheet_name,
        size_threshold=args.threshold,
        time_limit=args.time_limit,
        verbose=args.verbose
    )


if __name__ == "__main__":
    main()
