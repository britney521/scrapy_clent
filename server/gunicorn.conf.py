import multiprocessing
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

bind = os.getenv('GUNICORN_BIND', '127.0.0.1:8000')
workers = int(os.getenv('GUNICORN_WORKERS', str(max(2, multiprocessing.cpu_count() * 2 + 1))))
threads = int(os.getenv('GUNICORN_THREADS', '2'))
timeout = int(os.getenv('GUNICORN_TIMEOUT', '120'))
accesslog = str(BASE_DIR / 'logs' / 'gunicorn_access.log')
errorlog = str(BASE_DIR / 'logs' / 'gunicorn_error.log')
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')
capture_output = True
