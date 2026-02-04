"""
Interactive Room Merging Application Server
Run this to get a full interactive web interface for room merging
"""
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import pandas as pd
import json
import os
import sys
from pathlib import Path
import subprocess
import traceback

app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')
CORS(app)

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
UPLOAD_FOLDER = PROJECT_ROOT / 'uploads'
RESULTS_FOLDER = PROJECT_ROOT / 'results'
UPLOAD_FOLDER.mkdir(exist_ok=True)

app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

def run_merging(input_file):
    """Run the merging.py script on the input file"""
    try:
        # Prepare output paths
        output_file = RESULTS_FOLDER / 'IPL_merge_result.xlsx'
        merged_file = RESULTS_FOLDER / 'phong_sau_gop.xlsx'
        
        # Run NEW FAST merging script with correct arguments
        result = subprocess.run(
            [
                'python', 
                'ipl_optimizer.py',  # ⚡ NEW: Ultra-fast optimizer
                '-i', str(input_file),
                '-o', str(output_file),
                '--merged-out', str(merged_file),
                '--threshold', '0',  # ⚡ Force greedy mode (ultra-fast!)
                '--verbose'  # Show progress
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout (much faster now!)
        )
        
        if result.returncode != 0:
            return {
                'success': False,
                'error': f"Merging failed: {result.stderr}"
            }
        
        return {
            'success': True,
            'output': result.stdout
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f"Error running merging: {str(e)}\n{traceback.format_exc()}"
        }

def export_results_to_json(excel_file):
    """Export Excel results to JSON with detailed room and subject info"""
    try:
        # Read the Excel file sheets
        summary_by_shift = pd.read_excel(excel_file, sheet_name="Summary")
        changes_df = pd.read_excel(excel_file, sheet_name="Room_Changes_Detail")
        groups_df = pd.read_excel(excel_file, sheet_name="Groups")
        merges_df = pd.read_excel(excel_file, sheet_name="Merges")
        
        # Calculate overall statistics
        total_initial = int(summary_by_shift["Initial Rooms"].sum())
        total_final = int(summary_by_shift["Final Rooms (Optimized)"].sum())
        total_saved = int(summary_by_shift["Rooms Reduced"].sum())
        efficiency = round((total_saved/total_initial*100), 1) if total_initial > 0 else 0
        
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
        
        # Process each row in changes_df (Shift/Campus level)
        for _, row in changes_df.iterrows():
            shift = str(row["Shift"])
            campus = str(row["Campus"])
            initial = int(row["Initial Rooms Count"])
            final = int(row["Final Rooms Count"])
            removed_count = int(row["Rooms Removed Count"])
            
            # Filter details for this specific shift and campus
            shift_groups = groups_df[
                (groups_df['Shift'].astype(str) == shift) & 
                (groups_df['Campus'].astype(str) == campus)
            ]
            
            shift_merges = merges_df[
                (merges_df['Shift'].astype(str) == shift) & 
                (merges_df['Campus'].astype(str) == campus)
            ]
            
            # Build detailed lists for kept rooms
            kept_rooms_detail = []
            for _, group in shift_groups.iterrows():
                room_name = str(group['Kept Room'])
                subject = str(group['Kept Subject'])
                total_students = int(group['Total Students'])
                capacity = int(group['Total Students'] + group['Remaining Capacity'])
                
                # Find which rooms merged INTO this room
                merged_into_here = shift_merges[shift_merges['To Room'].astype(str) == room_name]
                merged_sources = []
                for _, merge in merged_into_here.iterrows():
                    merged_sources.append({
                        'room': str(merge['From Room']),
                        'subject': str(merge['From Subject']),
                        'students': int(merge.get('From Students', 0)),
                        'capacity': int(merge.get('From Capacity', 0)),
                        'status': 'Merged' 
                    })

                kept_rooms_detail.append({
                    'name': room_name,
                    'subject': subject,
                    'students': total_students,
                    'capacity': capacity,
                    'merged_sources': merged_sources
                })
            
            # Build detailed lists for removed rooms
            removed_rooms_detail = []
            # We identify removed rooms by looking at Merges "From Room"
            for _, merge in shift_merges.iterrows():
                from_room = str(merge['From Room'])
                from_subject = str(merge['From Subject'])
                to_room = str(merge['To Room'])
                
                # "From" rooms in Merges are the removed ones
                removed_rooms_detail.append({
                    'name': from_room,
                    'subject': from_subject,
                    'students': int(merge.get('From Students', 0)),
                    'capacity': int(merge.get('From Capacity', 0)),
                    'merged_to': to_room,
                    'status': 'Removed'
                })
            
            detail = {
                "shift": shift,
                "campus": campus,
                "initial": initial,
                "final": final,
                "saved": removed_count,
                # Frontend expects objects now, or we need to update frontend to handle objects
                # For compatibility, we'll pass the detailed objects but mapped to ensure frontend JS can use them.
                "kept_rooms_data": kept_rooms_detail,
                "removed_rooms_data": removed_rooms_detail,
                
                # Keep simple lists for backward compatibility if needed, or just use new data
                "kept_rooms": [r['name'] for r in kept_rooms_detail],
                "removed_rooms": [r['name'] for r in removed_rooms_detail]
            }
            
            data["details"].append(detail)
        
        return {'success': True, 'data': data}
        
    except Exception as e:
        return {
            'success': False,
            'error': f"Error exporting results: {str(e)}\n{traceback.format_exc()}"
        }

@app.route('/')
def index():
    """Serve the main application page"""
    return render_template('index.html')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle file upload"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        if not (file.filename.endswith('.xlsx') or file.filename.endswith('.csv')):
            return jsonify({'success': False, 'error': 'Only .xlsx or .csv files are allowed'}), 400
        
        # Save the file
        ext = os.path.splitext(file.filename)[1]
        filename = f'input_data{ext}'
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        return jsonify({
            'success': True,
            'filename': filename,
            'filepath': filepath
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Upload failed: {str(e)}"
        }), 500

@app.route('/api/merge', methods=['POST'])
def merge():
    """Run the merging process"""
    try:
        data = request.get_json()
        input_file = data.get('filepath')
        
        if not input_file or not os.path.exists(input_file):
            return jsonify({
                'success': False,
                'error': 'Input file not found'
            }), 400
        
        # Run merging
        result = run_merging(input_file)
        
        if not result['success']:
            return jsonify(result), 500
        
        # Check if result file was created
        result_file = RESULTS_FOLDER / 'IPL_merge_result.xlsx'
        
        if not result_file.exists():
            return jsonify({
                'success': False,
                'error': 'Merging completed but result file not found'
            }), 500
        
        # Export to JSON
        json_result = export_results_to_json(result_file)
        
        if not json_result['success']:
            return jsonify(json_result), 500
        
        return jsonify({
            'success': True,
            'data': json_result['data'],
            'message': 'Merging completed successfully'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Merge failed: {str(e)}\n{traceback.format_exc()}"
        }), 500

@app.route('/api/results')
def get_results():
    """Get existing results if available"""
    try:
        result_file = RESULTS_FOLDER / 'IPL_merge_result.xlsx'
        
        if not result_file.exists():
            return jsonify({
                'success': False,
                'error': 'No results available yet'
            }), 404
        
        json_result = export_results_to_json(result_file)
        
        if not json_result['success']:
            return jsonify(json_result), 500
        
        return jsonify({
            'success': True,
            'data': json_result['data']
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    print("="*60)
    print("ROOM MERGING INTERACTIVE APPLICATION")
    print("="*60)
    print("\n[INFO] Starting server...")
    print("[INFO] Open your browser at: http://localhost:5000")
    print("[INFO] Press Ctrl+C to stop the server\n")
    print("="*60)
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
