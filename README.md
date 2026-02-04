# IPL Room Merging Optimization System

## System Overview

The **IPL Room Merging Optimization System** is a computational framework designed to minimize the physical resource allocation for exam scheduling. By analyzing room capacities, student counts, and subject constraints, the system identifies optimal or near-optimal configurations for merging under-utilized exam rooms. The implementation employs a hybrid algorithmic approach, utilizing Exact Integer Linear Programming (ILP) for precision on smaller datasets and Heuristic algorithms for scalability on larger instances.

## Technology Stack

The system utilizes a modern scientific computing stack centered around Python's optimization ecosystem.

| Technology | Role | Justification |
| :--- | :--- | :--- |
| **Python 3.x** | Core Language | Provides a robust standard library and extensive support for data science and optimization libraries. |
| **PuLP** | Modeling | An LP/MILP modeler written in Python. It allows for the symbolic definition of decision variables, objective functions, and constraints, abstracting the complexity of the underlying solver interface. |
| **CBC Solver** | Optimization | *Coin-OR Branch and Cut*. An open-source mixed integer linear programming solver used to calculate the exact solution for the mathematical model defined in PuLP. |
| **Pandas** | Data Processing | Enables high-performance ingestion, manipulation, and serialization of tabular data (Excel/CSV). Crucial for handling large scheduling datasets efficiently. |
| **OpenPyXL** | I/O Utility | A Python library to read/write Excel 2010 xlsx/xlsm/xltx/xltm files, used by Pandas for generating the final formatted reports. |

## Module Responsibilities

The codebase `src/ipl_optimizer.py` is organized into three primary functional units:

### 1. `MILPRoomOptimizer` (Exact Solver)
This module implements the exact optimization logic derived from the formal ILP specification.
*   **Responsibility**: Constructs the mathematical model where:
    *   Variables $y_j$ determine if a room remains open.
    *   Variables $x_{ij}$ represent the assignment of students from room $i$ to room $j$.
*   **Mechanism**: It defines the feasible solution space ($O(N^2)$ edges) and enforces all rigid constraints (capacity limits, subject separation). It invokes the CBC solver with a strict time limit (default: 30 seconds) to prevent execution stalls.

### 2. `GreedyBinPacker` (Heuristic Solver)
This module provides a fallback mechanism for datasets exceeding the computational capacity of the exact solver (typically $N > 15$).
*   **Responsibility**: Generates feasible assignment plans rapidly without guaranteeing global optimality.
*   **Mechanism**: Implements a **Multi-Pass Constructive Heuristic**. It executes five distinct bin-packing strategies sequentially:
    1.  Best-Fit (Ascending Student Count)
    2.  Best-Fit (Descending Student Count)
    3.  First-Fit (Descending Student Count)
    4.  Worst-Fit (Descending Student Count)
    5.  Best-Fit (Descending Capacity)
    The system then evaluates the objective function (number of open rooms) for each strategy and selects the mathematically superior result.

### 3. `process_exam_data` (Pipeline Controller)
This function acts as the controller for the execution pipeline.
*   **Control Flow**:
    1.  **Ingestion**: Reads and sanitizes input data.
    2.  **Partitioning**: Segregates data by unique `Shift` and `Campus` identifiers.
    3.  **Solver Selection**: Routes each partition to either `MILPRoomOptimizer` or `GreedyBinPacker` based on the number of rooms relative to the configured `threshold`.
    4.  **Aggregation**: Compiles results from all partitions into a unified report.

## Execution Workflow

1.  **Data Ingestion**: The system accepts an input file path via the Command Line Interface (CLI).
2.  **Validation**: Input data is scrubbed for consistency. Rows with missing mandated fields or non-numeric capacity values trigger specific exceptions.
3.  **Optimization Loop**:
    *   The system iterates through every unique Exam Shift.
    *   The `size_threshold` is checked against the group size.
    *   The appropriate solver computes the assignment vector.
    *   If the MILP solver encounters an error or timeout, the system automatically degrades to the Heuristic solver to ensure process continuity.
4.  **Reporting**: Final results are serialized into an Excel workbook containing detailed sheets for merged groups, room change statistics, and solver performance metrics.

## Constraints Implementation

All optimization logic adheres to three invariant rules:
*   **Capacity Invariant**: $\sum \text{Students} \le \text{Capacity}_{\text{target}}$
*   **Subject Disjointness**: A merged group assignment is invalid if the incoming room shares a subject identifier with the target room (unless $source == target$).
*   **Binary State**: A room is strictly categorized as either "Open" (retaining its students and potentially accepting others) or "Closed" (transferring all students to a single target).
