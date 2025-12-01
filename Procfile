# Procfile for local development with Honcho
# Usage: honcho start
#
# Queue architecture mirrors production systemd services:
# - default: general tasks (email, legal, misc project tasks)
# - downloads: file download tasks (download_project_file)
# - maintenance: cleanup/health check tasks (ensure_download_tasks_queued, checks_cleanup_stale_files)
# - docker-persistent: long-running container tasks (check_process_job)
# - docker-ephemeral: container orchestration/cleanup (checks_cancelling, checks_cleanup_failed_containers)

# Django development server
web: python manage.py runserver 8081

# Celery worker for general tasks
# Handles: default queue (email, legal tasks, misc), referrals, downloads
# --concurrency=1: Single worker process for local development
# --loglevel=info: Show task execution logs
# --pool=solo: Use solo pool (simplest, single-threaded, good for debugging)
worker: celery -A config worker -Q default,referrals,downloads --loglevel=info --concurrency=1 --pool=solo

# Celery worker for maintenance tasks (cleanup, health checks)
# Separate worker ensures maintenance tasks run even when main worker is busy
maintenance: celery -A config worker -Q maintenance --loglevel=info --concurrency=1 --pool=solo

# Celery worker for Docker-based manufacturability checks
# Handles both persistent (check_process_job) and ephemeral (cleanup) tasks
# In production these are separate services, but combined here for simplicity
docker: celery -A config worker -Q docker-persistent,docker-ephemeral --loglevel=info --concurrency=1 --pool=solo

# Celery Beat scheduler for periodic tasks
# --loglevel=debug: Show scheduling logs
# --schedule: SQLite database file for beat schedule
# Runs periodic tasks defined in CELERY_BEAT_SCHEDULE
beat: celery -A config beat --loglevel=debug --schedule=celerybeat-schedule.sqlite3
