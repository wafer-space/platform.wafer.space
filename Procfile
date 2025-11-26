# Procfile for local development with Honcho
# Usage: honcho start

# Django development server
web: python manage.py runserver 8081

# Celery worker for background tasks (file downloads, manufacturability checks)
# --concurrency=1: Single worker process for local development
# --loglevel=info: Show task execution logs
# --pool=solo: Use solo pool (simplest, single-threaded, good for debugging)
# -Q: Listen to specific queues (celery=default, manufacturability=project tasks, referrals=referral tasks)
worker: celery -A config worker -Q celery,manufacturability,referrals --loglevel=info --concurrency=1 --pool=solo

# Celery Beat scheduler for periodic tasks (auto-retry failed downloads)
# --loglevel=info: Show scheduling logs
# --schedule: SQLite database file for beat schedule (uses .sqlite3 extension for consistency)
# Runs periodic tasks defined in CELERY_BEAT_SCHEDULE (e.g., retry_failed_downloads every 5 minutes)
beat: celery -A config beat --loglevel=info --schedule=celerybeat-schedule.sqlite3
