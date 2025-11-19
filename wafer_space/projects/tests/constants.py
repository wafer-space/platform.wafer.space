"""Constants for project tests."""

# Test user credentials
TEST_PASSWORD = "testpass123"  # noqa: S105 - Test password constant

# HTTP status codes
HTTP_OK = 200
HTTP_FOUND = 302
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404

# File sizes (in bytes)
ONE_MB = 1048576  # 1 MB = 1024 * 1024
TEN_MB = 10485760  # 10 MB
FIVE_MB = 4718592  # ~4.5 MB

# Progress percentages
PROGRESS_HALF = 45
PROGRESS_COMPLETE = 100

# Pagination
DEFAULT_PAGE_SIZE = 2

# Test counts
EXPECTED_IP_RANGE_COUNT = 8
EXPECTED_USER_PROJECTS = 2  # Number of projects created for test user

# Worker tracking test values
TEST_WORKER_PID = 12345
