"""
Gunicorn production config for 漫展抽奖系统
Usage: gunicorn -c gunicorn.conf.py wsgi:app
"""
import multiprocessing

bind = "127.0.0.1:8000"
workers = 4
worker_class = "sync"
threads = 8
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
preload_app = True

loglevel = "info"
accesslog = "-"
errorlog = "-"

proc_name = "lottery_app"

backlog = 2048
