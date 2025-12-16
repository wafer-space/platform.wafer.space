# Procfile for local development with Honcho
# Usage: honcho start
#
# See docs/systemd-services.md for queue naming convention and task mappings.
# Network/filesystem restrictions in queue names don't apply in development.

web: python manage.py runserver 8081

# Fast worker: quick tasks (orchestration, email, metadata, general, fast docker)
worker-fast: celery -A config worker -Q none:ro:default,none:ro:checks-orch,mail:ro:email,http:ro:metadata,dock:ro:checks-fast --loglevel=info --concurrency=1 --pool=solo

# Slow worker: long-running tasks (downloads, slow docker, result saving)
worker-slow: celery -A config worker -Q http:rw:downloads,dock:ro:checks-slow,dock:rw:checks-save --loglevel=info --concurrency=2 --pool=threads

# Celery Beat scheduler
beat: celery -A config beat --loglevel=debug --schedule=celerybeat-schedule.sqlite3
