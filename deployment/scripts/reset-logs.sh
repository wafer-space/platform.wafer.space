#!/bin/bash
# Reset/clear all application log files
# Run as: sudo ./reset-logs.sh

set -e

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root"
    echo "Usage: sudo $0"
    exit 1
fi

LOG_DIR="/var/log/platform.wafer.space"
BACKUP_DIR="/var/backups/platform.wafer.space/logs"

# Parse command line arguments
BACKUP=true
FORCE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-backup)
            BACKUP=false
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Reset all application log files"
            echo ""
            echo "Options:"
            echo "  --no-backup    Skip backing up logs before resetting"
            echo "  --force        Don't ask for confirmation"
            echo "  -h, --help     Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Reset logs with backup and confirmation"
            echo "  $0 --no-backup        # Reset logs without backup"
            echo "  $0 --force            # Reset all logs without confirmation"
            echo ""
            echo "Note: This script also resets systemd journal logs for django services"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

echo "=== Platform.wafer.space Log Reset ==="
echo ""

# Check if log directory exists
if [ ! -d "$LOG_DIR" ]; then
    echo "Log directory does not exist: $LOG_DIR"
    echo "Creating directory..."
    mkdir -p "$LOG_DIR"
    chown django:django "$LOG_DIR"
    echo "✓ Log directory created"
    exit 0
fi

# List log files
echo "Log files to be reset:"
LOG_FILES=(
    "$LOG_DIR/restart.log"
    "$LOG_DIR/update.log"
)

# Find all .log files in the directory
while IFS= read -r -d '' file; do
    LOG_FILES+=("$file")
done < <(find "$LOG_DIR" -type f -name "*.log" -print0 2>/dev/null)

# Remove duplicates
mapfile -t LOG_FILES < <(printf "%s\n" "${LOG_FILES[@]}" | sort -u)

if [ ${#LOG_FILES[@]} -eq 0 ]; then
    echo "No log files found in $LOG_DIR"
    exit 0
fi

# Display files and their sizes
TOTAL_SIZE=0
for log_file in "${LOG_FILES[@]}"; do
    if [ -f "$log_file" ]; then
        SIZE=$(stat -f%z "$log_file" 2>/dev/null || stat -c%s "$log_file" 2>/dev/null || echo "0")
        SIZE_MB=$(echo "scale=2; $SIZE / 1048576" | bc 2>/dev/null || echo "0")
        echo "  - $log_file (${SIZE_MB}MB)"
        TOTAL_SIZE=$((TOTAL_SIZE + SIZE))
    fi
done

TOTAL_MB=$(echo "scale=2; $TOTAL_SIZE / 1048576" | bc 2>/dev/null || echo "0")
echo ""
echo "Total size: ${TOTAL_MB}MB"
echo ""

# Ask for confirmation unless --force is used
if [ "$FORCE" = false ]; then
    read -p "Do you want to proceed? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

# Backup logs if requested
if [ "$BACKUP" = true ]; then
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_ARCHIVE="$BACKUP_DIR/logs_backup_$TIMESTAMP.tar.gz"

    echo "Creating backup..."
    mkdir -p "$BACKUP_DIR"

    # Create temporary file list
    TEMP_LIST=$(mktemp)
    for log_file in "${LOG_FILES[@]}"; do
        if [ -f "$log_file" ]; then
            echo "$log_file" >> "$TEMP_LIST"
        fi
    done

    # Create archive
    if [ -s "$TEMP_LIST" ]; then
        tar -czf "$BACKUP_ARCHIVE" -T "$TEMP_LIST" 2>/dev/null || {
            echo "Warning: Some files could not be backed up"
        }
        rm "$TEMP_LIST"

        BACKUP_SIZE=$(stat -f%z "$BACKUP_ARCHIVE" 2>/dev/null || stat -c%s "$BACKUP_ARCHIVE" 2>/dev/null || echo "0")
        BACKUP_SIZE_MB=$(echo "scale=2; $BACKUP_SIZE / 1048576" | bc 2>/dev/null || echo "0")
        echo "✓ Backup created: $BACKUP_ARCHIVE (${BACKUP_SIZE_MB}MB)"
    else
        rm "$TEMP_LIST"
        echo "No files to backup"
    fi
fi

# Reset log files
echo ""
echo "Resetting log files..."
RESET_COUNT=0
for log_file in "${LOG_FILES[@]}"; do
    if [ -f "$log_file" ]; then
        # Truncate the file to 0 bytes (preserves permissions and ownership)
        truncate -s 0 "$log_file" && {
            echo "  ✓ Reset: $log_file"
            RESET_COUNT=$((RESET_COUNT + 1))
        } || {
            echo "  ✗ Failed: $log_file"
        }
    fi
done

echo ""
echo "=== Log Reset Complete ==="
echo "Reset $RESET_COUNT log file(s)"

if [ "$BACKUP" = true ] && [ -f "$BACKUP_ARCHIVE" ]; then
    echo "Backup saved to: $BACKUP_ARCHIVE"
fi

# Reset systemd journal logs for django services
echo ""
echo "Resetting systemd journal logs for django services..."

# Define services to clear journal logs for
SERVICES=(
    "django-gunicorn.service"
    "django-celery-none-ro-default.service"
    "django-celery-none-ro-checks-orch.service"
    "django-celery-none-ro-beat.service"
    "django-celery-mail-ro-email.service"
    "django-celery-http-rw-downloads.service"
    "django-celery-dock-ro-checks-fast.service"
    "django-celery-dock-ro-checks-slow.service"
    "django-celery-dock-rw-checks-save.service"
)

# Show current journal sizes
echo "Current journal sizes:"
for service in "${SERVICES[@]}"; do
    SIZE=$(journalctl -u "$service" --disk-usage 2>/dev/null | grep -oP 'Archived and active journals take up \K[^ ]+' || echo "0B")
    echo "  $service: $SIZE"
done

echo ""
if [ "$FORCE" = true ]; then
    RESET_JOURNAL=true
else
    read -p "Reset systemd journal logs? (y/N) " -n 1 -r
    echo
    RESET_JOURNAL=false
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        RESET_JOURNAL=true
    fi
fi

if [ "$RESET_JOURNAL" = true ]; then
    # Rotate journal logs
    echo "Rotating journal logs..."
    journalctl --rotate

    # Vacuum journal logs for each service
    echo "Clearing journal logs for django services..."
    for service in "${SERVICES[@]}"; do
        journalctl --vacuum-time=1s -u "$service" >/dev/null 2>&1 && {
            echo "  ✓ Cleared: $service"
        } || {
            echo "  ✗ Failed: $service"
        }
    done

    echo ""
    echo "✓ Systemd journal logs reset"
else
    echo "Skipped systemd journal reset"
fi

echo ""
echo "=== All Logs Reset Complete ==="
