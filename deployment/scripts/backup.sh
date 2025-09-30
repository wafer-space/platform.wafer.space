#!/bin/bash
# Backup platform.wafer.space database

BACKUP_DIR="/home/django/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/platform_wafer_space_$DATE.sql.gz"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Perform backup
pg_dump -h localhost -U platform_wafer_space platform_wafer_space | gzip > "$BACKUP_FILE"

# Keep only last 30 days of backups
find "$BACKUP_DIR" -name "platform_wafer_space_*.sql.gz" -mtime +30 -delete

# Log
echo "$(date): Backup completed: $BACKUP_FILE" >> /var/log/platform.wafer.space/backup.log
