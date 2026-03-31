"""
Simple API server for SCLE web UI.
For production, use a proper ASGI server.
"""

from flask import Flask, request, jsonify
import subprocess
import os

app = Flask(__name__, static_folder='.', static_url_path='')

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/run', methods=['POST'])
def run_task():
    data = request.json
    
    # This would normally call the SCLE Python API
    # For now, return a mock response
    return jsonify({
        'status': 'success',
        'session_id': 'mock-123',
        'iterations': 1,
        'tokens': 500,
        'artifacts': []
    })

if __name__ == '__main__':
    app.run(port=8080, debug=True)