# GDS File Download System

## Overview

The GDS (chip design) file download system allows users to submit URLs to large design files (up to 100GB) for background downloading with progress tracking, automatic URL rewriting, and security validation.

## Architecture

### Component Layers

```
Views → Services → Tasks → Models
```

- **Views**: User interface and request handling (not yet implemented)
- **Services** (`wafer_space/projects/services.py`): Business logic coordination
- **Tasks** (`wafer_space/projects/tasks.py`): Background download processing with Celery
- **Models** (`wafer_space/projects/models.py`): Data representation

This architecture prevents circular imports by maintaining clear dependency direction.

## Key Features

### 1. Automatic URL Rewriting

The system automatically converts common file hosting platform URLs to direct download URLs:

**Supported Platforms:**

- **GitHub**: `github.com/user/repo/blob/main/file.gds` → `raw.githubusercontent.com/user/repo/main/file.gds`
- **GitLab**: `gitlab.com/user/repo/-/blob/main/file.gds` → `gitlab.com/user/repo/-/raw/main/file.gds`
- **Dropbox**: `dropbox.com/s/abc?dl=0` → `dropbox.com/s/abc?dl=1`
- **Google Drive**: `drive.google.com/file/d/ID/view` → `drive.usercontent.google.com/download?id=ID&export=download&confirm=t`
- **OneDrive**: Adds `download=1` parameter to share links

**Implementation:** `wafer_space/projects/url_rewriters.py`

**Usage:**
```python
from wafer_space.projects.url_rewriters import URLRewriter

url = "https://github.com/user/repo/blob/main/design.gds"
rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)
# Returns: ("https://raw.githubusercontent.com/...", True, "Converted GitHub blob URL...")
```

### 2. Security Validation

Prevents SSRF (Server-Side Request Forgery) attacks and validates file accessibility:

**Security Checks:**

- **URL Scheme**: Only `http://` and `https://` allowed (blocks `file://`, `ftp://`, etc.)
- **Private IP Blocking**: Rejects localhost and private IP ranges:
  - RFC 1918: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
  - RFC 3927: `169.254.0.0/16` (link-local)
  - RFC 4193: `fc00::/7` (IPv6 unique local)
  - Loopback: `127.0.0.0/8`, `::1/128`
- **File Size Limits**: Maximum 100GB (advertised Content-Length checked
  before download; actual received bytes enforced during download)
- **File Accessibility**: HEAD request confirms file exists and is accessible
  (falls back to a streaming GET when the server rejects HEAD or omits
  Content-Length)
- **Early Content Check**: The leading bytes of the download are validated
  against accepted signatures (GDS/OASIS/zip/gzip/bzip2/xz), so a server
  answering with an HTML error or interstitial page aborts after the first
  chunk instead of downloading the complete response

**Implementation:** `wafer_space/projects/security.py`

**Usage:**
```python
from wafer_space.projects.security import URLValidator, SecurityValidationError

try:
    result = URLValidator.validate_url(url)
    # Returns: {
    #     "file_size": 1048576,
    #     "content_type": "application/octet-stream",
    #     "etag": '"abc123"',
    #     "supports_range": True
    # }
except SecurityValidationError as e:
    # Handle security validation failure
    pass
```

### 3. Chunked Downloads with Resume Capability

Large files are downloaded in 1MB chunks with automatic resume support:

**Features:**

- **Streaming Download**: 1MB chunks to minimize memory usage
- **HTTP Range Requests**: Automatically resumes from byte position after interruption
- **Fallback**: If server doesn't support Range requests, starts from beginning
- **Hash Calculation**: MD5 and SHA1 calculated incrementally during download
- **Progress Tracking**: Updates Celery task state every chunk (~1MB)
- **Database Updates**: Saves progress every 5% (reduces writes from 10,000 to ~20 per 100GB file)

**Implementation:** `wafer_space/projects/tasks.py` - `_download_with_progress()` and `download_project_file()`

### 4. Progress Tracking

Two-tier progress tracking system optimized for large files:

**Celery Task State** (Real-time):
- Updated every chunk (~1MB) via `task.update_state()`
- Accessible via `AsyncResult(task_id).info`
- No database overhead

**Database** (Persistent):
- Updated every 5% progress
- `last_activity` timestamp for monitoring
- Prevents 10,000+ DB writes for large files

**Implementation:** `wafer_space/projects/services.py` - `ProjectFileService.get_download_progress()`

### 5. File Replacement

Only one active file per project, with automatic replacement tracking:

**Features:**

- Database constraint ensures one active file per project
- When submitting new file, previous active file is marked inactive
- `replaced_by` field tracks replacement chain
- `is_active` boolean indicates current file

**Database Schema:**
```python
# wafer_space/projects/models.py
class ProjectFile(models.Model):
    is_active = models.BooleanField(default=True)
    replaced_by = models.ForeignKey("self", null=True, blank=True, ...)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(is_active=True),
                name="one_active_file_per_project",
            ),
        ]
```

### 6. Hash Verification

Supports optional MD5 and SHA1 hash verification:

**User-Provided Hashes:**
- `expected_hash_md5`: Optional MD5 hash from user
- `expected_hash_sha1`: Optional SHA1 hash from user

**Calculated Hashes:**
- `hash_md5`: Calculated during download
- `hash_sha1`: Calculated during download
- `hash_verified`: Boolean indicating match

**Verification:**
```python
# After download completes
hash_verified, errors = project_file.verify_hash()
if not hash_verified:
    # Handle hash mismatch
    pass
```

## Usage Example

### Complete Flow

```python
from wafer_space.projects.services import ProjectFileService
from wafer_space.projects.models import Project

# 1. Submit file URL (from view)
project = Project.objects.get(id=project_id)
url = "https://github.com/user/repo/blob/main/design.gds"

project_file, metadata = ProjectFileService.submit_file_from_url(
    project=project,
    url=url,
    expected_hash_md5="abc123...",  # Optional
    expected_hash_sha1="def456...",  # Optional
)

# metadata contains:
# {
#     "url_rewritten": True,
#     "rewrite_reason": "Converted GitHub blob URL to raw content URL",
#     "file_size": 104857600,
#     "content_type": "application/octet-stream",
#     "supports_range": True
# }

# 2. Check progress (from view, polling every few seconds)
progress = ProjectFileService.get_download_progress(project_file)
# {
#     "status": "downloading",
#     "progress": 45,  # percentage
#     "current": 47185920,  # bytes downloaded
#     "total": 104857600,  # total bytes
#     "message": "Downloaded 47,185,920 of 104,857,600 bytes"
# }

# 3. After completion, verify hash
if project_file.download_status == ProjectFile.DownloadStatus.COMPLETED:
    hash_verified, errors = project_file.verify_hash()
    if hash_verified:
        # File is ready for manufacturability check
        pass
```

## Database Fields

### ProjectFile Model Changes

**URL Tracking:**
- `original_url`: User-submitted URL (before rewriting)
- `source_url`: Actual download URL (after rewriting)

**Download Progress:**
- `download_status`: PENDING, DOWNLOADING, COMPLETED, FAILED, LOCAL_UPLOAD
- `download_started_at`: Timestamp when download started
- `download_completed_at`: Timestamp when download completed/failed
- `download_error`: Error message if failed
- `download_task_id`: Celery task ID for progress tracking
- `last_activity`: Last progress update timestamp

**File Replacement:**
- `is_active`: Whether this is the current file
- `replaced_by`: ForeignKey to replacement file

**Hash Verification:**
- `expected_hash_md5`: User-provided MD5 (optional)
- `expected_hash_sha1`: User-provided SHA1 (optional)
- `hash_md5`: Calculated MD5
- `hash_sha1`: Calculated SHA1
- `hash_verified`: Whether hashes match

## Error Handling

### Retry Strategy

Downloads use exponential backoff retry:
- **Max Retries**: 5 attempts
- **Retry Delay**: 60 seconds × 2^(retry_count)
  - Attempt 1: 60 seconds
  - Attempt 2: 120 seconds
  - Attempt 3: 240 seconds
  - Attempt 4: 480 seconds
  - Attempt 5: 960 seconds (16 minutes)

### Security Errors

Security validation errors are NOT retried:
- Invalid URL scheme
- Private IP address
- File size exceeds 100GB
- Unresolvable hostname

### Download Errors

Network/file errors trigger retry:
- Connection timeouts
- Network interruptions
- Server errors (500, 502, 503, 504)
- Incomplete downloads

### Cleanup

Temporary files are automatically cleaned up:
- On successful completion
- On final failure (after max retries)
- Stored in: `/tmp/wafer_space_downloads/`

## Testing

### Unit Tests

**URL Rewriters** (22 tests):
```bash
uv run pytest wafer_space/projects/tests/test_url_rewriters.py -v
```

**Security Validation** (27 tests):
```bash
uv run pytest wafer_space/projects/tests/test_security.py -v
```

**All Tests** (62 tests total):
```bash
uv run pytest wafer_space/projects/tests/ -v
```

### Test Coverage

- ✅ URL rewriting for 5 platforms
- ✅ Security validation (SSRF prevention)
- ✅ Edge cases (already rewritten URLs, invalid inputs)
- ✅ Private IP range blocking
- ✅ File size limits
- ❌ Service layer (not yet tested)
- ❌ Download task with resume (not yet tested)
- ❌ Browser tests (not yet implemented)

## Configuration

### Celery Settings

```python
# config/settings/base.py

CELERY_TASK_ROUTES = {
    "wafer_space.projects.tasks.download_project_file": {"queue": "downloads"},
}

# Separate queue for downloads (2 workers recommended)
# celery -A config worker -Q downloads --concurrency=2
```

### File Size Limit

```python
# wafer_space/projects/security.py
URLValidator.MAX_FILE_SIZE = 100 * 1024 * 1024 * 1024  # 100GB
```

### Chunk Size

```python
# wafer_space/projects/tasks.py
_download_with_progress(task, project_file, temp_path, chunk_size=1024*1024)  # 1MB
```

## Future Enhancements

### Not Yet Implemented

1. **Forms**: URL submission form with validation feedback
2. **Views**: Progress tracking page, file submission UI
3. **Templates**: User interface for file submission and monitoring
4. **Notifications**: Email, Web Push, in-app notifications on completion
5. **Browser Tests**: End-to-end testing of complete user flow
6. **Admin Interface**: Django admin for monitoring downloads

### Planned Features

1. **Bandwidth Throttling**: Configurable download speed limits
2. **Multiple Files**: Support for projects with multiple design files
3. **Download Scheduling**: Queue management for high-load periods
4. **Storage Backend**: S3-compatible storage (currently uses local filesystem)
5. **Checksum Algorithms**: Support for SHA256, SHA512
6. **Mirror Selection**: Automatic mirror selection for faster downloads

## Troubleshooting

### Download Stalls

Check `last_activity` field:
```python
from django.utils import timezone
from datetime import timedelta

stalled = ProjectFile.objects.filter(
    download_status=ProjectFile.DownloadStatus.DOWNLOADING,
    last_activity__lt=timezone.now() - timedelta(minutes=30)
)
```

### Progress Not Updating

Verify Celery worker is running:
```bash
# Check active tasks
celery -A config inspect active

# Check task result
from celery.result import AsyncResult
task = AsyncResult(task_id)
print(task.state, task.info)
```

### Private IP Blocked

This is intentional security behavior. Use public URLs or configure firewall rules to allow outbound connections to the IP address.

### File Size Check Fails

Servers that omit the `Content-Length` header (chunked transfer encoding)
or reject HEAD requests are accepted with an unknown size; the 100GB limit
is then enforced on actual received bytes during download. Validation only
fails when the URL is unreachable or advertises an invalid or oversized
Content-Length.

## Security Considerations

### SSRF Prevention

The security validation is mandatory and cannot be bypassed. This prevents:
- Internal network scanning via localhost/private IPs
- File system access via file:// URLs
- Protocol injection attacks
- Server resource exhaustion via oversized files

### Hash Verification

MD5 and SHA1 are used for **file integrity verification only**, not cryptographic security. This is industry standard for design file verification.

### Temporary File Security

Temporary files are stored with restrictive permissions:
- Directory: `/tmp/wafer_space_downloads/`
- Permissions: User-only read/write
- Cleanup: Automatic on completion or failure

## Performance Considerations

### Memory Usage

- **Chunk Size**: 1MB chunks keep memory usage constant
- **Streaming**: File never fully loaded into memory
- **Hash Calculation**: Incremental, no memory overhead

### Database Load

- **Progress Updates**: Every 5% (~20 writes per 100GB file)
- **Last Activity**: Single field update, no joins
- **Task State**: Stored in Celery backend, not application DB

### Network Efficiency

- **Resume Support**: Prevents re-downloading partial files
- **HEAD Requests**: Validate before downloading
- **Connection Reuse**: Requests library connection pooling

## Related Documentation

- **Architecture**: See CLAUDE.md for overall project structure
- **Models**: See `wafer_space/projects/models.py` for field definitions
- **Tasks**: See `wafer_space/projects/tasks.py` for Celery task implementation
- **Security**: See `wafer_space/projects/security.py` for validation details
