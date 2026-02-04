"""
Post-processing script to display detailed merging results summary
Run this after merging.py to see detailed English summary
"""
import pandas as pd
from pathlib import Path

def display_summary(result_file="results/IPL_merge_result.xlsx"):
    """Display detailed summary of merging results in English"""
    
    # Read the Excel file
    summary_by_shift = pd.read_excel(result_file, sheet_name="Summary")
    changes_df = pd.read_excel(result_file, sheet_name="Room_Changes_Detail")
    
    print("\n" + "="*80)
    print("ROOM MERGING RESULTS SUMMARY")
    print("="*80)
    
    total_initial = summary_by_shift["Initial Rooms"].sum()
    total_final = summary_by_shift["Final Rooms (Optimized)"].sum()
    total_saved = summary_by_shift["Rooms Reduced"].sum()
    
    print(f"\n[OVERALL RESULTS]")
    print(f"   Initial Rooms:  {total_initial}")
    print(f"   Final Rooms:    {total_final}")
    print(f"   Rooms Saved:    {total_saved}")
    print(f"   Efficiency:     {(total_saved/total_initial*100):.1f}% reduction")
    
    print("\n[BREAKDOWN BY SHIFT & CAMPUS]")
    print("-"*80)
    
    for _, row in changes_df.iterrows():
        shift = row["Shift"]
        campus = row["Campus"]
        initial = row["Initial Rooms Count"]
        final = row["Final Rooms Count"]
        removed_count = row["Rooms Removed Count"]
        kept = row["Kept Rooms"]
        removed = row["Removed Rooms"]
        
        print(f"\n> Shift {shift}, Campus {campus}:")
        print(f"   Initial: {initial} rooms  ->  Final: {final} rooms  (Saved: {removed_count})")
        
        # Check if removed is a valid string (not NaN)
        if pd.notna(removed) and removed != "None":
            kept_list = kept.split(", ")
            removed_list = removed.split(", ")
            
            print(f"   [KEPT] ({len(kept_list)}): {kept[:60]}{'...' if len(kept) > 60 else ''}")
            print(f"   [REMOVED] ({len(removed_list)}): {removed[:60]}{'...' if len(removed) > 60 else ''}")
        else:
            print(f"   [INFO] All rooms kept (no merging possible)")
    
    print("\n" + "="*80)
    print("[SUCCESS] Analysis complete!")
    print("\n[DOCS] See MERGING_RESULTS_EXPLANATION.md for detailed documentation")
    print("[DOCS] See QUICK_SUMMARY.md for quick reference")
    print("="*80)

if __name__ == "__main__":
    import sys
    result_file = sys.argv[1] if len(sys.argv) > 1 else "results/IPL_merge_result.xlsx"
    display_summary(result_file)
