"""
Bench (Processing Server) Status Web UI

Simple status dashboard showing:
- Current processing jobs
- GPU status and utilization
- Queue depth
- Recent completed jobs
- System health
"""

from flask import Flask, render_template, jsonify
import subprocess
import os
import psutil
from datetime import datetime
from typing import Dict, List, Optional
import json


def create_app():
    """Create Flask app for bench status page."""
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')

    # Store job queue in memory (replace with Redis in production)
    app.job_queue = []
    app.completed_jobs = []
    app.current_job = None

    @app.route('/')
    def index():
        """Main status dashboard."""
        return render_template('status.html')

    @app.route('/api/status')
    def api_status():
        """Get full system status as JSON."""
        return jsonify({
            'timestamp': datetime.utcnow().isoformat(),
            'system': get_system_status(),
            'gpu': get_gpu_status(),
            'queue': {
                'current': app.current_job,
                'pending': len(app.job_queue),
                'jobs': app.job_queue[:10]  # First 10
            },
            'recent': app.completed_jobs[-10:]  # Last 10
        })

    @app.route('/api/health')
    def api_health():
        """Simple health check endpoint."""
        gpu = get_gpu_status()
        return jsonify({
            'status': 'healthy' if gpu.get('available') else 'degraded',
            'gpu_available': gpu.get('available', False),
            'uptime': get_uptime(),
            'queue_depth': len(app.job_queue)
        })

    @app.route('/api/gpu')
    def api_gpu():
        """Get detailed GPU info."""
        return jsonify(get_gpu_status())

    @app.route('/api/queue')
    def api_queue():
        """Get queue status."""
        return jsonify({
            'current': app.current_job,
            'pending': app.job_queue,
            'completed': app.completed_jobs[-20:]
        })

    return app


def get_system_status() -> Dict:
    """Get system resource usage."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        return {
            'cpu_percent': cpu_percent,
            'memory': {
                'total_gb': round(memory.total / (1024**3), 1),
                'used_gb': round(memory.used / (1024**3), 1),
                'percent': memory.percent
            },
            'disk': {
                'total_gb': round(disk.total / (1024**3), 1),
                'used_gb': round(disk.used / (1024**3), 1),
                'percent': round(disk.percent, 1)
            }
        }
    except Exception as e:
        return {'error': str(e)}


def get_gpu_status() -> Dict:
    """Get NVIDIA GPU status using nvidia-smi."""
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu',
             '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return {'available': False, 'error': 'nvidia-smi failed'}

        lines = result.stdout.strip().split('\n')
        gpus = []

        for i, line in enumerate(lines):
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 6:
                gpus.append({
                    'id': i,
                    'name': parts[0],
                    'memory_total_mb': int(parts[1]),
                    'memory_used_mb': int(parts[2]),
                    'memory_free_mb': int(parts[3]),
                    'utilization_percent': int(parts[4]),
                    'temperature_c': int(parts[5])
                })

        return {
            'available': True,
            'count': len(gpus),
            'gpus': gpus
        }

    except FileNotFoundError:
        return {'available': False, 'error': 'nvidia-smi not found'}
    except subprocess.TimeoutExpired:
        return {'available': False, 'error': 'nvidia-smi timeout'}
    except Exception as e:
        return {'available': False, 'error': str(e)}


def get_uptime() -> str:
    """Get system uptime."""
    try:
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{days}d {hours}h {minutes}m"
    except:
        return "unknown"


# Job management functions (called by processing pipeline)
def add_job(app, job_info: Dict):
    """Add job to queue."""
    job_info['queued_at'] = datetime.utcnow().isoformat()
    job_info['status'] = 'pending'
    app.job_queue.append(job_info)


def start_job(app, job_id: str):
    """Mark job as in-progress."""
    for job in app.job_queue:
        if job.get('id') == job_id:
            job['status'] = 'processing'
            job['started_at'] = datetime.utcnow().isoformat()
            app.current_job = job
            app.job_queue.remove(job)
            break


def complete_job(app, job_id: str, success: bool = True, result: Dict = None):
    """Mark job as completed."""
    if app.current_job and app.current_job.get('id') == job_id:
        app.current_job['status'] = 'completed' if success else 'failed'
        app.current_job['completed_at'] = datetime.utcnow().isoformat()
        app.current_job['result'] = result
        app.completed_jobs.append(app.current_job)
        app.current_job = None

        # Keep only last 100 completed jobs
        if len(app.completed_jobs) > 100:
            app.completed_jobs = app.completed_jobs[-100:]
