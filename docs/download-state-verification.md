# Download State Verification System

## Overview

The download state verification system ensures that file downloads are properly tracked and orphaned downloads are detected and recovered.

## Download States

1. **PENDING**: File uploaded, no Celery task created yet
2. **QUEUED**: Task created and in Celery queue
3. **DOWNLOADING**: Worker actively downloading file
4. **COMPLETED**: Download successful
5. **FAILED**: Download failed or orphaned

## Verification Process

### PENDING Files
- System creates Celery task if missing
- Auto-transitions to QUEUED when task created

### QUEUED Files
- Verifies task exists in Celery reserved queue
- Auto-transitions to DOWNLOADING when task starts
- Marks as FAILED if task not found

### DOWNLOADING Files
- Verifies task in Celery active list
- Verifies worker process (PID) exists
- Marks as FAILED if task not running or PID dead

## Configuration

- **Production**: Check every 60 seconds
- **Development**: Check every 30 seconds

## Monitoring

Check logs for:
```
State check: X created, Y orphaned, Z verified
```

## Troubleshooting

**File stuck in PENDING**:
- Check Celery worker is running
- Check logs for task creation

**File stuck in QUEUED**:
- Check Celery queue has capacity
- Verify worker is accepting tasks

**File stuck in DOWNLOADING**:
- Check worker didn't crash (PID verification)
- Check network connectivity

All orphaned files trigger auto-retry if enabled.
