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
