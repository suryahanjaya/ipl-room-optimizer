"""
Export Excel results to JSON for web visualization
Run this after merging.py to generate JSON data for the web interface
"""
import pandas as pd
import json
from pathlib import Path

def export_to_json(result_file="results/IPL_merge_result.xlsx", output_file="results/merge_data.json"):
    """Export Excel data to JSON format for web interface"""
    
    # Read the Excel file
    summary_by_shift = pd.read_excel(result_file, sheet_name="Summary")
    changes_df = pd.read_excel(result_file, sheet_name="Room_Changes_Detail")
    
    # Calculate overall statistics
    total_initial = int(summary_by_shift["Initial Rooms"].sum())
    total_final = int(summary_by_shift["Final Rooms (Optimized)"].sum())
    total_saved = int(summary_by_shift["Rooms Reduced"].sum())
    efficiency = round((total_saved/total_initial*100), 1)
    
    # Prepare data structure
    data = {
        "overall": {
            "initial_rooms": total_initial,
            "final_rooms": total_final,
            "rooms_saved": total_saved,
            "efficiency_percent": efficiency
        },
        "details": []
    }
    
    # Process each row
    for _, row in changes_df.iterrows():
        shift = str(row["Shift"])
        campus = str(row["Campus"])
        initial = int(row["Initial Rooms Count"])
        final = int(row["Final Rooms Count"])
        removed_count = int(row["Rooms Removed Count"])
        kept = str(row["Kept Rooms"]) if pd.notna(row["Kept Rooms"]) else ""
        removed = str(row["Removed Rooms"]) if pd.notna(row["Removed Rooms"]) else ""
        
        detail = {
            "shift": shift,
            "campus": campus,
            "initial": initial,
            "final": final,
            "saved": removed_count,
            "kept_rooms": kept.split(", ") if kept and kept != "None" else [],
            "removed_rooms": removed.split(", ") if removed and removed != "None" else []
        }
        
        data["details"].append(detail)
    
    # Write to JSON file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"[SUCCESS] Data exported to {output_file}")
    print(f"[INFO] You can now open the web interface to view results")
    
    return output_path

if __name__ == "__main__":
    import sys
    result_file = sys.argv[1] if len(sys.argv) > 1 else "results/IPL_merge_result.xlsx"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "results/merge_data.json"
    export_to_json(result_file, output_file)
