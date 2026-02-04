# Codebase Audit and Technical Compliance Report

## 1. Executive Summary

This document presents a technical audit of the `ipl_optimizer.py` implementation, evaluating its adherence to the Integer Linear Programming (ILP) specifications defined in `IPL (4).pdf` (referenced as `ILP_F.pdf`). It also analyzes the structural and algorithmic evolution of the system by comparing it against archival implementations (`merging.py` and `heuristic.py`). The audit confirms that the core ILP model is implemented correctly, though with specific functional extensions not present in the theoretical formulation.

## 2. Codebase Audit

### 2.1 Implementation Architecture
The current system (`src/ipl_optimizer.py`) adopts a hybrid optimization strategy encapsulated in a modular Object-Oriented design.

*   **Design Pattern**: Strategy Pattern for solver selection.
*   **Encapsulation**: Critical logic is housed within the `MILPRoomOptimizer` and `GreedyBinPacker` classes, separating the optimization algorithms from data ingestion and reporting layers.
*   **Adaptive Flow**: The control flow in `process_exam_data` dynamically selects the optimization strategy based on problem size ($N$).

### 2.2 Constraints and Limitations
*   **Subject Disjointness**: The system enforces a constraint that merged rooms must not contain overlapping subjects (unless it is the host room itself). This is a rigid constraint that may limit potential merges but prevents exam conflict.
*   **Time Complexity**: The MILP solver's feasibility construction is $O(N^2)$, and the Branch-and-Bound process is exponential in the worst case. The time limit of 30 seconds (default) acts as a hard constraint on optimality.
*   **Heuristic Nature**: The greedy solver utilizes a deterministic constructive approach. It does not guarantee global optimality but ensures a feasible solution in polynomial time ($O(S \cdot N^2)$ where $S$ is the number of strategies).

## 3. Comparative Analysis with Archival Code

### 3.1 Comparison with `archives/merging.py` (Exact Solver)

**Functional Difference**: The current implementation adds robustness mechanisms including time limits and fallback logic.

**Evidence 1: Time Limit Implementation**
*   **Archived (`merging.py`)**: The solver runs indefinitely until optimal.
    ```python
    solver = pulp.PULP_CBC_CMD(msg=False)
    ```
*   **Current (`ipl_optimizer.py`)**: The solver is constrained to prevents hanging.
    ```python
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=self.time_limit)
    ```

**Evidence 2: Error Handling and Fallback**
*   **Archived (`merging.py`)**: Uses a simple loop; failures raise unhandled exceptions.
*   **Current (`ipl_optimizer.py`)**: Implements a try-catch block to downgrade to the heuristic solver upon failure.
    ```python
    try:
        # ... MILP instantiation ...
    except Exception as milp_error:
        print(f"[WARNING] MILP failed... Falling back to Greedy Heuristic")
        solver = GreedyBinPacker(...)
    ```

### 3.2 Comparison with `archives/heuristic.py` (Heuristic Solver)

**Algorithmic Difference**: The heuristic strategy has shifted from an *Iterative Local Improvement* model to a *Multi-Pass Constructive* model.

**Evidence 3: Solver Strategy**
*   **Archived (`heuristic.py`)**: Attempts to pack bins and then iteratively improves the solution by moving items ("passes").
    ```python
    # archives/heuristic.py
    while improved and passes < 5:
        # ... logic to close bins by moving members ...
    ```
*   **Current (`ipl_optimizer.py`)**: Runs five distinct sorting strategies and selects the best result. It does not perform post-construction local search.
    ```python
    # src/ipl_optimizer.py
    results = [
        try_best_fit(order_asc),
        try_best_fit(order_desc),
        try_first_fit(order_desc),
        try_worst_fit(order_desc),
        try_best_fit(order_cap),
    ]
    best_result = min(results, key=lambda x: count_open(x[0]))
    ```

## 4. ILP Compliance Verification (`ILP_F.pdf`)

This section rigorously verifies the implementation of concepts defined in `ILP_F.pdf`.

### 4.1 Mathematical Model: Compliance Status (100% Compliant)
The core mathematical model for room merging (Objective function and Constraints C1-C4) is **fully implemented** as per the specification.

| Equation in `ILP_F.pdf` | Description | Implementation Proof (`src/ipl_optimizer.py`) |
| :--- | :--- | :--- |
| **$min \sum y_j$** | Minimize Open Rooms | `model += pulp.lpSum(y_vars[j] for j in range(self.num_rooms))` |
| **(C1) $\sum x_{ij} = 1$** | Assignment Uniqueness | `pulp.lpSum(x_vars[(source, dest)] ...) == 1` |
| **(C2) $x_{ij} \le y_j$** | Dependent Activation | `x_vars[(source, dest)] <= y_vars[dest]` |
| **(C3) $x_{jj} = y_j$** | Self-Assignment Logic | `y_vars[room_idx] == x_vars[(room_idx, room_idx)]` |
| **(C4) $\sum b_i x_{ij} \le a_j y_j$** | Capacity Limit | `total_students <= self.capacities[dest] * y_vars[dest]` |

### 4.2 Algorithm 1: Compliance Status (Partially Compliant)
The PDF specifies a "Custom Branch-and-Bound" algorithm (Algorithm 1) involving specific heuristics for branching (lines 178-180 in PDF). The current code **does not** implement this manual branching logic. Instead, it delegates the entire solving process to the CBC solver.

*   **PDF Specification**: "Choose variable $x_k$ with fractional value... Determine priority based on closeness to 0 or 1."
*   **Actual Code**: 
    ```python
    # src/ipl_optimizer.py (Line 399-400)
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=self.time_limit)
    status = model.solve(solver)
    ```
*   **Implication**: While the *model* is identical, the *search strategy* relies on Coin-OR CBC's internal black-box optimizations rather than the specific heuristic proposed in the paper. This is a standard industry practice for stability but functionally deviates from the paper's algorithmic pseudo-code.

### 4.3 Deviations and Extensions

**Extension: Subject Distinctness Constraint**
The implementation includes a constraint ensuring that assignments do not mix identical subjects in the same room (unless self-assigned). This constraint is **not** present in the formal mathematical model of `ILP_F.pdf`.

*   **Code Location**: `src/ipl_optimizer.py` lines 370-382.
    ```python
    # Additional constraint: Distinct subjects per destination room
    for dest in range(self.num_rooms):
        for subject, room_indices in subject_index.items():
            # ...
            model += (
                pulp.lpSum(subject_assignments) <= 1,
                f"SubjectDistinct_{dest}_{subject}"
            )
    ```

## 5. ILP Concept Audit Summary

| Concept from `ILP_F.pdf` | Status | Implementation Details |
| :--- | :--- | :--- |
| **Binary Decision Variables** | Implemented | `y_vars` and `x_vars` are defined as `pulp.LpBinary`. |
| **Linear Objective** | Implemented | Standard summation minimization. |
| **Capacity Constraints** | Implemented | Explicitly modeled as C4. |
| **Branch-and-Bound** | **Modified** | Replaced custom implementation with CBC solver call. |
| **LP Relaxation** | **Implicit** | Handled internally by CBC's pre-solve and bounding phases. |

## 6. Language and Neutrality Review

The codebase (`src/ipl_optimizer.py`) has been reviewed for language neutrality.
*   **Findings**: The implementation logic is technical and precise. Previous comments that may have claimed "optimal" results for the heuristic have been adjusted to describe the strategy (e.g., "aims to maximize space utilization") rather than the outcome.
*   **Status**: The current codebase adheres to the requirement for neutral, technical documentation within the docstrings.
