import os

# Gunicorn production configuration file for Render

# Bind to 0.0.0.0 on the port specified by the environment
bind = "0.0.0.0:" + os.environ.get("PORT", "5000")

# Concurrency & Worker setup
# Since Render Free Tier has limited CPU, 2 workers with 4 threads using the "gthread" worker class
# offers optimal concurrent request processing (total 8 concurrency) without bloating RAM.
workers = 2
threads = 4
worker_class = "gthread"

# Timeouts
timeout = 120            # Wait up to 120s for worker response (prevents premature SIGKILL on cold starts)
graceful_timeout = 30    # Grace period before killing worker on shutdown
keepalive = 5            # Keep connection open for subsequent requests (HTTP Keep-Alive)

# Memory & Process Health
# Prevent memory leaks from slowly growing and hitting Render's 512MB RAM limit by recycling workers
max_requests = 1000
max_requests_jitter = 100

# Logging
loglevel = "info"
accesslog = "-"          # Send access log to stdout
errorlog = "-"           # Send error log to stderr
