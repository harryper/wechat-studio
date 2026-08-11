# Gunicorn config for wechat-studio Web.
# Single-user, single-pod: 2 workers is enough. Preview/publish are short
# sync calls (cli.py subprocess); 60s timeout covers slow WeChat API.
# Actual heavy work (image generation, theme learning) is NOT done here.

import os


bind = "0.0.0.0:9997"

# Workers: 2 sync workers (matches video-studio). Single-user traffic only.
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
worker_class = "sync"

# Timeout: 60s is plenty — preview is a few seconds, publish includes
# WeChat API upload (token + image upload) and may take 10-30s.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "10"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))

# Memory-leak guard: recycle workers after N requests.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "500"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "100"))

# Logging
accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "/app/logs/access.log")
errorlog = os.environ.get("GUNICORN_ERROR_LOG", "/app/logs/error.log")
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
