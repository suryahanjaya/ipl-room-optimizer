"""
Room Merging Application - Main Entry Point
Run this file to start the interactive web application
"""
from src.web.server import app
import webbrowser
import threading
import time

def open_browser():
    """Open browser after a short delay"""
    time.sleep(1.5)
    webbrowser.open('http://localhost:5000')

if __name__ == '__main__':
    print("="*60)
    print("ROOM MERGING INTERACTIVE APPLICATION")
    print("="*60)
    print("\n[INFO] Starting server...")
    print("[INFO] Opening browser at: http://localhost:5000")
    print("[INFO] Press Ctrl+C to stop the server\n")
    print("="*60)
    
    # Open browser in background
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    # Run Flask app
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
