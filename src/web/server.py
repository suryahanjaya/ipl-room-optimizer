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
import threading
import uuid
import re
from pathlib import Path
import subprocess
import traceback
from datetime import datetime
import time

app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')
CORS(app)

# Global task storage
TASK_STATUS = {}

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
UPLOAD_FOLDER = PROJECT_ROOT / 'uploads'
RESULTS_FOLDER = PROJECT_ROOT / 'results'
UPLOAD_FOLDER.mkdir(exist_ok=True)

app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

def optimization_worker(task_id, input_file, mode):
    """
    Worker thread function to run optimization and update status
    """
    try:
        TASK_STATUS[task_id]['status'] = 'running'
        TASK_STATUS[task_id]['progress'] = 0
        TASK_STATUS[task_id]['message'] = 'Initializing optimization engine...'
        
        # Prepare output paths with TIMESTAMP
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_filename = f"Result_{timestamp}.xlsx"
        output_file = RESULTS_FOLDER / output_filename
        
        # Configure arguments based on mode
        cmd = [
            'python', 
            '-u', # ⚡ Force unbuffered stdout for real-time progress
            'src/ipl_optimizer.py',
            '-i', str(input_file),
            '-o', str(output_file),
            '--verbose'
        ]
        
        if mode == 'deep':
            # 🧠 Deep Optimization
            cmd.extend(['--threshold', '200', '--time-limit', '600'])
            TASK_STATUS[task_id]['message'] = 'Running Deep Optimization (MILP)...'
        else:
            # 🚀 Fast Mode
            cmd.extend(['--threshold', '0'])
            TASK_STATUS[task_id]['message'] = 'Running Fast Optimization...'

        # Use Popen to read output in real-time
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        total_groups = 0
        processed_groups = 0
        
        # Read output line by line
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            
            # Check for total groups count
            if "Total Groups:" in line:
                try:
                    total_groups = int(line.split(":")[1].strip())
                    TASK_STATUS[task_id]['total'] = total_groups
                except:
                    pass
            
            # Check for progress update: "Processing [i/N]: ..."
            # Regex to capture processing index
            match = re.search(r"Processing \[(\d+)/(\d+)\]:", line)
            if match:
                current = int(match.group(1))
                total = int(match.group(2))
                total_groups = total # Update just in case
                
                percentage = int((current / total) * 100)
                TASK_STATUS[task_id]['progress'] = percentage
                TASK_STATUS[task_id]['message'] = f"Processing Group {current} of {total}..."
            
            # Also capture basic "Processing:" log for fallback
            elif "Processing:" in line and total_groups > 0:
                # Fallback estimation if regex fails
                 processed_groups += 1
                 percentage = int((processed_groups / total_groups) * 100)
                 TASK_STATUS[task_id]['progress'] = min(99, percentage)
        
        # Wait for process to finish
        process.wait()
        
        if process.returncode != 0:
             raise Exception("Optimizer process failed or returned errors.")
        
        # Process output
        TASK_STATUS[task_id]['message'] = 'Finalizing results...'
        TASK_STATUS[task_id]['progress'] = 99
        
        # Export logic inside worker
        if not output_file.exists():
             raise Exception("Output file was not created.")
        
        json_result = export_results_to_json(output_file)
        
        if not json_result['success']:
             raise Exception(json_result.get('error', 'Failed to parse results'))
             
        # Add download URL
        json_result['data']['download_url'] = f"/results/{output_file.name}"
        
        TASK_STATUS[task_id]['result'] = json_result['data']
        TASK_STATUS[task_id]['status'] = 'completed'
        TASK_STATUS[task_id]['progress'] = 100
        TASK_STATUS[task_id]['message'] = 'Optimization Completed!'
        
    except Exception as e:
        TASK_STATUS[task_id]['status'] = 'failed'
        TASK_STATUS[task_id]['error'] = str(e)
        print(f"Task {task_id} failed: {e}")
        traceback.print_exc()

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
    """Start the merging process as a background task"""
    try:
        data = request.get_json()
        input_file = data.get('filepath')
        mode = data.get('mode', 'fast') # Default to fast
        
        if not input_file or not os.path.exists(input_file):
            return jsonify({
                'success': False,
                'error': 'Input file not found'
            }), 400
        
        # Create task ID
        task_id = str(uuid.uuid4())
        
        # Initialize task status
        TASK_STATUS[task_id] = {
            'status': 'pending',
            'progress': 0,
            'message': 'Starting...',
            'result': None
        }
        
        # Start background thread
        thread = threading.Thread(
            target=optimization_worker,
            args=(task_id, input_file, mode)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': 'Optimization started'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Merge start failed: {str(e)}"
        }), 500

@app.route('/api/status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """Get status of a background task"""
    task = TASK_STATUS.get(task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Task not found'}), 404
        
    return jsonify({
        'success': True,
        'status': task['status'],
        'progress': task['progress'],
        'message': task['message'],
        'result': task.get('result')
    })

@app.route('/results/<path:filename>')
def download_result(filename):
    """Serve result files"""
    from flask import send_from_directory
    return send_from_directory(RESULTS_FOLDER, filename, as_attachment=True)

if __name__ == '__main__':
    print("="*60)
    print("ROOM MERGING INTERACTIVE APPLICATION")
    print("="*60)
    print("\n[INFO] Starting server...")
    print("[INFO] Open your browser at: http://localhost:5000")
    print("[INFO] Press Ctrl+C to stop the server\n")
    print("="*60)
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
