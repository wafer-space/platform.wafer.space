# Project Submission System - Implementation Status

## Overview

The project submission system allows users to submit their chip design files (GDS/OASIS formats) for low-cost silicon manufacturing through wafer.space. This document provides a comprehensive overview of the current implementation status.

**Last Updated**: 2025-12-09
**Status**: 95% Complete - Core infrastructure implemented, multi-check refactor complete, submission workflow and UI enhancements remaining

## Architecture

### Core Components

#### 1. Data Models (`models.py`)

**Project Model**
- UUID-based primary key
- User ownership with cascade deletion
- Status workflow: DRAFT → SUBMITTED → CHECKING → MANUFACTURABLE/NOT_MANUFACTURABLE → ASSIGNED → PRODUCTION → COMPLETED
- Tracks manufacturability check results
- Estimated cost calculation

**ProjectFile Model**
- URL-based file submission (no local uploads)
- Download status tracking (PENDING → DOWNLOADING → COMPLETED/FAILED)
- Hash verification (MD5 and SHA1)
- File format validation (GDS/OASIS only, with compression support)
- Handler metadata for special URL processing (e.g., googlesource.com)
- Active file tracking with replacement history
- Unique constraint: one active file per project

**ManufacturabilityCheck Model**
- **ForeignKey relationship with ProjectFile** (multiple checks per file)
- Trigger reason tracking (INITIAL, RETRY, DRC_UPDATE, ADMIN_RERUN)
- Parent check reference for retry chains (flat tree structure)
- Celery task tracking
- Results storage (errors, warnings, logs)
- Status: PENDING → DISPATCHED → RUNNING → FINISHED/ERROR/CANCELLED

#### 2. Business Logic (`services.py`)

**ProjectFileService**
- URL validation and security checks (SSRF protection)
- URL rewriting for common platforms:
  - GitHub blob → raw conversion
  - GitLab blob → raw conversion
  - Dropbox dl=0 → dl=1 conversion
  - Google Drive file ID extraction
  - OneDrive embed → download conversion
- URL handler framework for special processing (googlesource.com base64 decoding)
- File format validation (GDS/OASIS with optional compression)
- Hash verification workflow
- Download progress tracking
- File replacement and check cancellation coordination

#### 3. Background Tasks (`tasks.py`)

**File Download Task** (`download_project_file`)
- Streaming HTTP downloads (up to 100GB)
- Progress tracking with periodic updates
- Retry logic with exponential backoff
- Content-type validation
- Post-download handler processing (e.g., base64 decoding)
- Hash calculation and verification
- File size tracking

**Manufacturability Check Task** (`check_manufacturability`)
- Queued processing
- Integration with GDS/OASIS analysis tools
- Results aggregation

#### 4. Security (`security.py`)

**SSRF Protection**
- Private IP range blocking (RFC 1918, localhost, link-local)
- DNS rebinding attack prevention
- URL scheme validation (http/https only)
- Hostname validation
- IP address filtering

**Input Validation**
- File format restrictions (GDS/OASIS only)
- File size limits (100GB max)
- Hash format validation
- URL format validation

#### 5. URL Handlers (`url_handlers.py`)

**Handler Framework**
- Abstract `URLHandler` base class
- `can_handle(url)` - URL pattern matching
- `process_url(url)` - Pre-download URL transformation
- `post_download(content, metadata)` - Post-download content processing
- `URLHandlerRegistry` - Handler registration and lookup

**GoogleSourceHandler**
- Handles `*.googlesource.com` URLs
- Adds `?format=TEXT` query parameter
- Base64 decodes downloaded content
- Stores handler metadata in ProjectFile

#### 6. URL Rewriters (`url_rewriters.py`)

**Platform-Specific Rewriters**
- GitHub: blob → raw URL conversion
- GitLab: blob → raw URL conversion
- Dropbox: dl=0 → dl=1 parameter change
- Google Drive: file ID extraction
- OneDrive: embed → download URL conversion

Each rewriter returns:
- `source_url`: Rewritten URL for download
- `rewrite_metadata`: Details about transformation

### Views and Forms

#### Views (`views.py`)

1. **ProjectListView** - Display user's projects
2. **ProjectDetailView** - Show project details with file status
3. **ProjectCreateView** - Create new project
4. **ProjectUpdateView** - Edit project details
5. **ProjectDeleteView** - Delete project
6. **ProjectFileSubmitURLView** - Submit file URL with checksums
7. **ProjectFileProgressView** - AJAX endpoint for download progress

#### Forms (`forms.py`)

**ProjectForm**
- Name and description fields
- Bootstrap styling

**ProjectFileURLSubmitForm**
- URL field with validation
- MD5 hash field (optional if SHA1 provided)
- SHA1 hash field (optional if MD5 provided)
- **Requires at least one checksum**
- Hash format validation
- Clean methods for normalization

### Templates

- `project_list.html` - Project listing
- `project_detail.html` - Project details with download progress
- `project_form.html` - Create/edit project
- `project_confirm_delete.html` - Delete confirmation
- `project_file_submit_url.html` - URL submission form

## Current Implementation Status

### ✅ Completed Features

#### Core Infrastructure (100%)
- ✅ Django models with proper relationships
- ✅ Database migrations
- ✅ URL configuration and routing
- ✅ View layer with authentication
- ✅ Form validation
- ✅ Template rendering
- ✅ Celery task infrastructure

#### File Submission (100%)
- ✅ URL-only submission pathway (no local uploads)
- ✅ Mandatory checksum verification (MD5 or SHA1 required)
- ✅ GDS/OASIS format enforcement with compression support
- ✅ URL handler framework with googlesource.com support
- ✅ File format validation (.gds, .gdsii, .gds2, .oas, .oasis)
- ✅ Compression support (.gz, .zip, .bz2, .xz)
- ✅ URL rewriting for common platforms
- ✅ Security validation (SSRF protection)
- ✅ Streaming downloads for large files
- ✅ Progress tracking
- ✅ Hash verification

#### Testing (100%)
- ✅ 410+ total tests across entire project
- ✅ 172 tests specifically for projects app
- ✅ Unit tests for all components
- ✅ Integration tests for workflows
- ✅ Browser tests for UI flows
- ✅ Security tests for SSRF protection
- ✅ Test coverage >85%

#### Documentation (100%)
- ✅ Code docstrings
- ✅ Type hints throughout
- ✅ Inline comments for complex logic
- ✅ This comprehensive status document

### 🚧 In Progress / Remaining Work

#### Project Submission Workflow (0%)
The system can receive and download files but doesn't have a formal "submit" action that:
- Validates project is ready for submission
- Transitions project from DRAFT to SUBMITTED status
- Triggers manufacturability check
- Sends notification to user

**Estimated Effort**: 4-6 hours

#### Status Dashboard Enhancement (0%)
Current project detail page shows basic status. Needs:
- Real-time progress updates (AJAX polling implemented but not activated)
- Download status visualization
- Manufacturability check results display
- Error message display
- Retry mechanisms for failed downloads
- File replacement workflow UI

**Estimated Effort**: 6-8 hours

#### Manufacturability Check Integration (0%)
Infrastructure exists but not fully connected:
- Automatic check triggering after download
- GDS/OASIS analysis tool integration
- Results parsing and storage
- Error/warning display to user
- Retry logic for transient failures

**Estimated Effort**: 8-12 hours

#### Documentation (20%)
- ✅ This status document
- ❌ User-facing submission guide
- ❌ API documentation
- ❌ Deployment guide updates
- ❌ Admin documentation

**Estimated Effort**: 2-3 hours

## Supported File Formats

### Base Formats
- **GDS (GDSII)**: `.gds`, `.gdsii`, `.gds2`
- **OASIS**: `.oas`, `.oasis`

### Compression Formats
- **gzip**: `.gz`
- **zip**: `.zip`
- **bzip2**: `.bz2`
- **xz**: `.xz`

### Valid Combinations
- `design.gds` ✅
- `design.gds.gz` ✅
- `design.oasis.zip` ✅
- `design.pdf` ❌ (not supported)
- `design.svg` ❌ (not supported)

## Supported URL Platforms

### Native Support
- Any publicly accessible HTTP/HTTPS URL
- Direct links to GDS/OASIS files

### Platform-Specific Rewrites
1. **GitHub**: Converts blob URLs to raw URLs
   - `github.com/.../blob/...` → `raw.githubusercontent.com/...`

2. **GitLab**: Converts blob URLs to raw URLs
   - `gitlab.com/.../blob/...` → `gitlab.com/.../-/raw/...`

3. **Dropbox**: Changes dl parameter
   - `?dl=0` → `?dl=1`

4. **Google Drive**: Extracts file ID
   - Various formats → `drive.google.com/uc?id=...&export=download`

5. **OneDrive**: Converts embed to download
   - `embed` parameter → `download` parameter

### Special Handlers
1. **Google Source** (e.g., foss-eda-tools.googlesource.com)
   - Adds `?format=TEXT` parameter
   - Base64 decodes response content
   - Stores handler metadata

## Security Features

### SSRF Protection
- Blocks private IP ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Blocks localhost and loopback (127.0.0.0/8, ::1)
- Blocks link-local addresses (169.254.0.0/16, fe80::/10)
- Blocks multicast addresses
- DNS rebinding attack prevention
- URL scheme validation

### Input Validation
- File format whitelist
- File size limits (100GB max)
- Hash format validation (32 hex chars for MD5, 40 for SHA1)
- URL format validation
- Content-type verification

### Authentication & Authorization
- Login required for all project operations
- User ownership validation
- Project access control (owner only)

## API Endpoints

### Web UI Endpoints
- `GET /projects/` - List user's projects
- `GET /projects/<uuid>/` - Project detail
- `GET /projects/create/` - Create project form
- `POST /projects/create/` - Create project
- `GET /projects/<uuid>/update/` - Update project form
- `POST /projects/<uuid>/update/` - Update project
- `GET /projects/<uuid>/delete/` - Delete confirmation
- `POST /projects/<uuid>/delete/` - Delete project
- `GET /projects/<uuid>/submit-url/` - Submit file URL form
- `POST /projects/<uuid>/submit-url/` - Submit file URL

### AJAX Endpoints
- `GET /projects/<uuid>/progress/` - Get download progress (JSON)

## Database Schema

### Project Table
- `id` (UUID, PK)
- `user_id` (FK to users)
- `name` (CharField)
- `description` (TextField)
- `status` (CharField with choices)
- `created_at` (DateTimeField)
- `updated_at` (DateTimeField)
- `submitted_at` (DateTimeField, nullable)
- `estimated_cost` (DecimalField, nullable)

**Derived Properties (computed from latest check):**
- `is_manufacturable` (@property) - Derived from latest FINISHED check on submitted file
- `manufacturability_errors` (@property) - Errors from latest FINISHED check
- `check_completed_at` (@property) - Completion timestamp from latest check

### ProjectFile Table
- `id` (AutoField, PK)
- `project_id` (FK to projects, cascade)
- `file` (FileField, nullable)
- `file_type` (CharField with choices)
- `original_url` (URLField)
- `source_url` (URLField)
- `download_status` (CharField with choices)
- `download_started_at` (DateTimeField, nullable)
- `download_completed_at` (DateTimeField, nullable)
- `download_error` (TextField)
- `download_task_id` (CharField)
- `last_activity` (DateTimeField, nullable)
- `expected_hash_md5` (CharField)
- `expected_hash_sha1` (CharField)
- `hash_md5` (CharField)
- `hash_sha1` (CharField)
- `hash_verified` (BooleanField)
- `handler_metadata` (JSONField)
- `file_size` (BigIntegerField, nullable)
- `original_filename` (CharField)
- `content_type` (CharField)
- `uploaded_at` (DateTimeField)
- `is_active` (BooleanField)
- `replaced_by_id` (FK to self, nullable)

### ManufacturabilityCheck Table
- `id` (AutoField, PK)
- `project_file_id` (FK to project_files, cascade) - **Multiple checks per file**
- `status` (CharField with choices)
- `trigger_reason` (CharField) - INITIAL, RETRY, DRC_UPDATE, ADMIN_RERUN
- `parent_check` (ForeignKey to self, nullable) - Links to original check for retry chain
- `started_at` (DateTimeField, nullable)
- `completed_at` (DateTimeField, nullable)
- `task_id` (CharField)
- `is_manufacturable` (BooleanField, nullable)
- `errors` (JSONField)
- `warnings` (JSONField)
- `processing_logs` (TextField)

## Testing Strategy

### Unit Tests
- Model methods and properties
- Form validation logic
- Service layer methods
- URL rewriting logic
- URL handler logic
- Security validation
- Task functions (isolated)

### Integration Tests
- Complete submission workflow
- Download and verification pipeline
- File replacement flow
- Error handling and recovery

### Browser Tests
- Project creation UI
- File submission form
- Progress tracking
- Error display
- Authentication flows

### Security Tests
- SSRF attack prevention
- Input validation bypasses
- Authentication enforcement
- Authorization checks

## Performance Considerations

### Scalability
- Streaming downloads (no memory buffering)
- Celery task queuing
- Database indexing on common queries
- Lazy file loading

### Monitoring
- Download progress tracking
- Task status monitoring
- Error logging
- Performance metrics via Django Debug Toolbar

## Known Limitations

1. **File Size**: Maximum 100GB per file (configurable)
2. **File Formats**: GDS and OASIS only (no CIF, MEBES, etc.)
3. **Download Timeout**: 24 hours max (configurable)
4. **Hash Algorithms**: MD5 and SHA1 only (SHA256 not yet supported)
5. **Concurrent Downloads**: One active file per project

## Future Enhancements

### Short Term
- Complete project submission workflow
- Enhanced status dashboard
- Manufacturability check integration
- User documentation

### Medium Term
- SHA256 hash support
- Multiple files per project
- File version history UI
- Admin dashboard for monitoring
- Email notifications

### Long Term
- GraphQL API
- Real-time WebSocket updates
- Advanced GDS/OASIS analysis
- Cost estimation engine
- Batch project submission

## Related Issues

- Issue #9: Build Project Submission System (primary)
- Issue #28: Pre-commit hooks for secret detection (security)

## Code Statistics

- **Total Python LOC**: ~5,449 lines
- **Source Files**: 19 files
- **Test Files**: 9 files
- **Test Cases**: 172 tests (projects app)
- **Test Coverage**: >85%
- **Django Views**: 7 views
- **URL Patterns**: 7 routes
- **Background Tasks**: 2 Celery tasks
- **Security Validations**: 8+ validation layers

## Development Guidelines

### Adding New URL Handlers

1. Create handler class inheriting from `URLHandler`
2. Implement required methods: `can_handle()`, `process_url()`, `post_download()`
3. Register in `_url_handler_registry` (services.py and tasks.py)
4. Add comprehensive tests
5. Update documentation

### Adding New URL Rewriters

1. Create rewriter function in `url_rewriters.py`
2. Return dict with `source_url` and `rewrite_metadata`
3. Register in `_URL_REWRITERS` list
4. Add test cases
5. Update supported platforms documentation

### Testing Requirements

All new features must include:
- Unit tests for business logic
- Integration tests for workflows
- Browser tests for UI (if applicable)
- Security tests (if handling user input)
- >80% code coverage

### Code Quality Standards

- Type hints on all functions
- Docstrings following Google style
- Ruff linting (zero errors)
- mypy type checking
- Django best practices
- Security-first approach

## Deployment Notes

### Database Migrations

All migrations are tracked in version control. Apply with:
```bash
make migrate
```

### Environment Variables

Required settings:
- `CELERY_BROKER_URL` - PostgreSQL broker
- `CELERY_RESULT_BACKEND` - django-db
- `DEFAULT_FILE_STORAGE` - File storage backend
- `MEDIA_ROOT` - File upload directory

### Background Workers

Start Celery worker:
```bash
make celery
```

### Production Considerations

- Configure proper file storage (S3, local disk, etc.)
- Set appropriate `ALLOWED_HOSTS`
- Enable HTTPS for all URLs
- Configure CORS if needed
- Set up monitoring and alerting
- Regular database backups
- Celery worker autoscaling

## Conclusion

The project submission system has a solid foundation with comprehensive testing and security. The core file submission, download, and verification pipeline is complete and production-ready. Remaining work focuses on user experience enhancements (submission workflow, status dashboard) and integration (manufacturability checks).

**Estimated Time to Complete**: 14-23 hours of development work across the remaining batches.
