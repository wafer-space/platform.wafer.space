# Procfile for local development with Honcho
# Usage: honcho start

# Django development server
web: python manage.py runserver 8081

# Celery worker for background tasks (file downloads, manufacturability checks)
worker: celery -A config worker --loglevel=info
