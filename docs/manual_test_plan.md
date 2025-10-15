# Manual Test Plan - Wafer.space Platform

**Version:** 1.0
**Date:** 2025-10-15
**Status:** All features implemented and tested
**Test Duration:** ~45-60 minutes for complete run

---

## Prerequisites

### Test Environment Setup
- [ ] Server running on `http://localhost:8081`
- [ ] Fresh database (or test account available)
- [ ] Celery worker running (`make celery`)
- [ ] Test files prepared (see Test Data section)

### Starting the Application
```bash
# Terminal 1: Start Django server
make runserver

# Terminal 2: Start Celery worker
make celery
```

### Test Data Required

**Test Files:**
- Small GDS file (< 10MB) for local upload testing
- Test URL for file download (GitHub raw file recommended)

**Recommended Test URLs:**
```
GitHub (public):
https://github.com/[user]/[repo]/blob/main/test.gds

Example working URL:
https://github.com/django/django/blob/main/README.rst
```

**Test Hashes (for verification testing):**
- Generate with: `md5sum your-file.gds`
- Generate with: `sha1sum your-file.gds`

---

## Test Execution Record

Tester: ___________________
Date: ___________________
Environment: ___________________
Result: PASS / FAIL (circle one)

---

## Section 1: User Authentication & Account Management

### Test 1.1: User Registration
**Feature:** New user signup
**Priority:** Critical

**Steps:**
1. Navigate to `http://localhost:8081`
2. Click "Sign Up" in navigation bar
3. Fill in registration form:
   - Email: `test+[timestamp]@example.com`
   - Password: `SecureTest123!`
   - Password confirmation: `SecureTest123!`
4. Submit form

**Expected Results:**
- ✅ Registration succeeds
- ✅ Redirected to home page or dashboard
- ✅ User is logged in automatically
- ✅ Username/email displayed in navigation bar

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 1.2: GitHub OAuth Login
**Feature:** OAuth authentication
**Priority:** Critical

**Prerequisites:** Valid GitHub account

**Steps:**
1. Log out if currently logged in
2. Navigate to `http://localhost:8081/accounts/login/`
3. Click "Sign in with GitHub" button
4. Authorize application (if prompted)

**Expected Results:**
- ✅ Redirected to GitHub OAuth page
- ✅ NO intermediate confirmation page (direct redirect)
- ✅ Successfully authenticated
- ✅ Redirected back to platform
- ✅ User is logged in

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 1.3: User Logout
**Feature:** Session termination
**Priority:** High

**Steps:**
1. Ensure you're logged in
2. Click username/profile in navigation
3. Click "Log Out"
4. Confirm logout if prompted

**Expected Results:**
- ✅ Successfully logged out
- ✅ Redirected to home page
- ✅ Login/Sign Up buttons visible again
- ✅ Protected pages redirect to login

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

## Section 2: Project Management (CRUD Operations)

### Test 2.1: Create New Project
**Feature:** Project creation
**Priority:** Critical

**Prerequisites:** Logged in user

**Steps:**
1. Navigate to `http://localhost:8081/projects/`
2. Click "Create New Project" or similar button
3. Fill in project form:
   - Name: `Test Project [timestamp]`
   - Description: `This is a test project for manual QA testing`
4. Click "Save" or "Create"

**Expected Results:**
- ✅ Project created successfully
- ✅ Success message displayed
- ✅ Redirected to project detail page
- ✅ Project name and description visible
- ✅ Status shows "Draft"
- ✅ No file uploaded yet message displayed

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 2.2: View Project List
**Feature:** Project listing
**Priority:** High

**Prerequisites:** At least one project created

**Steps:**
1. Navigate to `http://localhost:8081/projects/`
2. Observe project list

**Expected Results:**
- ✅ All user's projects displayed
- ✅ Project name visible
- ✅ Creation date visible
- ✅ Status visible
- ✅ Projects sorted by creation date (newest first)
- ✅ Only user's own projects visible (security)

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 2.3: View Project Details
**Feature:** Project detail view
**Priority:** High

**Steps:**
1. From project list, click on a project name
2. Observe project detail page

**Expected Results:**
- ✅ Project name displayed prominently
- ✅ Description visible (if provided)
- ✅ Creation and modification dates visible
- ✅ "Edit" button visible
- ✅ "Delete" button visible
- ✅ "Submit File URL" button visible
- ✅ "Upload File" button visible
- ✅ File status section visible

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 2.4: Update Project
**Feature:** Project editing
**Priority:** Medium

**Steps:**
1. From project detail page, click "Edit"
2. Modify project name: `Test Project [timestamp] - Updated`
3. Modify description: `Updated description`
4. Click "Save"

**Expected Results:**
- ✅ Success message displayed
- ✅ Redirected to project detail page
- ✅ Updated name displayed
- ✅ Updated description displayed
- ✅ "Last modified" timestamp updated

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 2.5: Delete Project
**Feature:** Project deletion
**Priority:** Medium

**Steps:**
1. Create a new project for deletion testing
2. From project detail page, click "Delete"
3. Confirm deletion on confirmation page

**Expected Results:**
- ✅ Confirmation page displayed
- ✅ Warning about permanent deletion shown
- ✅ After confirmation, success message displayed
- ✅ Redirected to project list
- ✅ Deleted project no longer in list

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

## Section 3: File Submission via URL

### Test 3.1: Submit Valid File URL
**Feature:** URL-based file submission
**Priority:** Critical

**Prerequisites:** Project created, test URL prepared

**Steps:**
1. From project detail page, click "Submit File URL"
2. Enter URL: `https://github.com/django/django/blob/main/README.rst`
3. Leave hash fields empty (optional)
4. Click "Submit"

**Expected Results:**
- ✅ Success message: "File 'README.rst' submitted for download!"
- ✅ Message mentions URL rewriting: "(URL rewritten: Converted GitHub blob URL...)"
- ✅ Redirected to project detail page
- ✅ Active file section shows "README.rst"
- ✅ Status badge shows "Download Pending" or "Downloading"
- ✅ Progress bar visible (if download started)

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 3.2: Verify Download Progress Tracking
**Feature:** Real-time download progress
**Priority:** High

**Prerequisites:** File download in progress from Test 3.1

**Steps:**
1. Observe project detail page (should auto-refresh)
2. Watch progress bar update
3. Wait for download completion

**Expected Results:**
- ✅ Progress bar updates automatically (AJAX polling every 3 seconds)
- ✅ Percentage displayed (0-100%)
- ✅ Status message shows bytes downloaded
- ✅ When complete, status badge changes to "Download Completed"
- ✅ Progress bar shows 100%
- ✅ Page refreshes automatically when complete

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 3.3: Submit URL with Hash Verification
**Feature:** Hash verification
**Priority:** High

**Prerequisites:** Project created, file with known hash

**Steps:**
1. From project detail page, click "Submit File URL"
2. Enter valid URL
3. Enter MD5 hash (use correct hash for the file)
4. Enter SHA1 hash (use correct hash for the file)
5. Submit form
6. Wait for download completion

**Expected Results:**
- ✅ File downloads successfully
- ✅ Hash verification runs after download
- ✅ If hashes match: Success notification or indicator
- ✅ If hashes don't match: Warning or error displayed
- ✅ Hash verification status visible in project detail

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 3.4: URL Security Validation - Private IP
**Feature:** SSRF protection
**Priority:** Critical (Security)

**Steps:**
1. From project detail page, click "Submit File URL"
2. Enter private IP URL: `http://192.168.1.1/test.gds`
3. Submit form

**Expected Results:**
- ✅ Error message displayed
- ✅ Message contains "Security validation failed" or similar
- ✅ Message mentions private IP address
- ✅ Form not submitted
- ✅ No background task started

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 3.5: URL Security Validation - localhost
**Feature:** SSRF protection (localhost)
**Priority:** Critical (Security)

**Steps:**
1. From project detail page, click "Submit File URL"
2. Enter localhost URL: `http://localhost/test.gds`
3. Submit form

**Expected Results:**
- ✅ Error message: "Security validation failed"
- ✅ Message mentions "Cannot download from localhost"
- ✅ No download initiated

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 3.6: URL Security Validation - Invalid Scheme
**Feature:** URL scheme validation
**Priority:** High (Security)

**Steps:**
1. From project detail page, click "Submit File URL"
2. Enter file:// URL: `file:///etc/passwd`
3. Submit form

**Expected Results:**
- ✅ Error message displayed
- ✅ Message mentions invalid or disallowed scheme
- ✅ Only http:// and https:// allowed

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 3.7: URL Rewriting - GitHub
**Feature:** Automatic URL rewriting
**Priority:** Medium

**Steps:**
1. From project detail page, click "Submit File URL"
2. Enter GitHub blob URL: `https://github.com/user/repo/blob/main/file.txt`
3. Submit form

**Expected Results:**
- ✅ Success message includes "(URL rewritten: Converted GitHub blob URL to raw content URL)"
- ✅ File downloads successfully
- ✅ Original URL stored in database
- ✅ Rewritten URL used for actual download

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 3.8: URL Rewriting - Dropbox
**Feature:** Dropbox URL rewriting
**Priority:** Medium

**Steps:**
1. Submit Dropbox share URL ending with `?dl=0`
2. Observe success message

**Expected Results:**
- ✅ URL rewritten to `?dl=1` (direct download)
- ✅ Success message mentions URL rewriting
- ✅ Download proceeds successfully

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 3.9: Invalid URL Handling
**Feature:** URL validation
**Priority:** Medium

**Steps:**
1. Submit form with invalid URL: `not-a-url`
2. Submit form with empty URL
3. Submit form with URL to non-existent domain

**Expected Results:**
- ✅ Invalid URL: Error message about URL format
- ✅ Empty URL: Error message "URL is required"
- ✅ Non-existent domain: Error about connection failure or DNS resolution

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

## Section 4: File Upload (Local)

### Test 4.1: Upload Small File
**Feature:** Local file upload
**Priority:** Critical

**Prerequisites:** Small test file (< 10MB)

**Steps:**
1. From project detail page, click "Upload File"
2. Click "Choose File" or drag-drop file
3. Select file type: "Design File"
4. Leave hash fields empty
5. Click "Upload"

**Expected Results:**
- ✅ File uploads successfully
- ✅ Success message displayed
- ✅ Redirected to project detail page
- ✅ File name displayed in active file section
- ✅ Status shows "Local Upload" (not "Downloading")
- ✅ File size displayed
- ✅ No progress bar (instant upload)

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 4.2: Upload with Hash Verification
**Feature:** Local upload with hash check
**Priority:** High

**Prerequisites:** File with known MD5/SHA1

**Steps:**
1. From project detail page, click "Upload File"
2. Choose file
3. Enter correct MD5 hash
4. Enter correct SHA1 hash
5. Upload

**Expected Results:**
- ✅ Upload succeeds
- ✅ Hash verification passes
- ✅ Success indicator for hash verification

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 4.3: Upload with Incorrect Hash
**Feature:** Hash mismatch detection
**Priority:** High

**Steps:**
1. Upload file with intentionally wrong MD5 hash: `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`
2. Observe results

**Expected Results:**
- ✅ Upload completes
- ✅ Warning or error about hash mismatch
- ✅ Details show expected vs actual hash
- ✅ File still available but marked as unverified

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 4.4: Invalid File Extension
**Feature:** File type validation
**Priority:** Medium

**Steps:**
1. Attempt to upload file with invalid extension (e.g., `.exe`, `.sh`)
2. Submit form

**Expected Results:**
- ✅ Error message about invalid file type
- ✅ List of allowed extensions shown
- ✅ Upload rejected

**Allowed Extensions:**
zip, rar, 7z, tar, gz, gds, gdsii, cif, pdf, png, jpg, svg

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

## Section 5: File Replacement

### Test 5.1: Replace Existing File
**Feature:** File replacement tracking
**Priority:** High

**Prerequisites:** Project with existing file

**Steps:**
1. Navigate to project with active file
2. Click "Submit File URL" or "Upload File"
3. Submit a different file
4. Observe results

**Expected Results:**
- ✅ New file submission succeeds
- ✅ Previous file automatically marked as inactive
- ✅ New file becomes active file
- ✅ Only ONE active file per project (database constraint)
- ✅ Old file data preserved in database
- ✅ Replacement relationship tracked

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

## Section 6: Access Control & Security

### Test 6.1: Project Ownership Enforcement
**Feature:** Authorization checks
**Priority:** Critical (Security)

**Prerequisites:** Two user accounts

**Steps:**
1. Login as User A
2. Create a project, note the project UUID from URL
3. Logout
4. Login as User B
5. Manually navigate to User A's project: `http://localhost:8081/projects/{UUID}/`

**Expected Results:**
- ✅ Access denied (403 Forbidden) OR
- ✅ Redirected to project list OR
- ✅ Error message: "Permission denied"
- ✅ User B cannot view User A's project

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 6.2: Unauthenticated Access
**Feature:** Login requirement
**Priority:** Critical (Security)

**Steps:**
1. Logout completely
2. Attempt to access:
   - Project list: `http://localhost:8081/projects/`
   - Project detail: `http://localhost:8081/projects/{UUID}/`
   - File upload page
3. Observe behavior

**Expected Results:**
- ✅ Redirected to login page for all protected URLs
- ✅ Login page URL includes `?next=` parameter
- ✅ After login, redirected to originally requested page

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 6.3: Edit/Delete Protection
**Feature:** Modification access control
**Priority:** High (Security)

**Steps:**
1. As User B, attempt to construct direct POST/DELETE requests to User A's project
2. Or use browser developer tools to modify forms

**Expected Results:**
- ✅ Modification attempts rejected
- ✅ Permission denied error
- ✅ No changes applied to User A's project

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

## Section 7: Edge Cases & Error Handling

### Test 7.1: File Size Limit Enforcement
**Feature:** Maximum file size validation
**Priority:** High

**Steps:**
1. Submit URL to a file larger than 100GB (if available)
2. Or mock the response (requires technical setup)

**Expected Results:**
- ✅ Error message: "File size exceeds maximum allowed size"
- ✅ Size comparison shown (e.g., "150GB exceeds 100GB limit")
- ✅ Download not initiated

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 7.2: Network Interruption Handling
**Feature:** Download retry mechanism
**Priority:** Medium

**Prerequisites:** Ability to interrupt network (disconnect WiFi mid-download)

**Steps:**
1. Start large file download
2. Disconnect network during download
3. Reconnect network
4. Observe behavior

**Expected Results:**
- ✅ Download retries automatically (up to 5 attempts)
- ✅ Error message shown if retries exhausted
- ✅ Exponential backoff between retries (60s, 120s, 240s, 480s, 960s)
- ✅ Download status shows retry count

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 7.3: Concurrent Downloads
**Feature:** Multiple file handling
**Priority:** Medium

**Steps:**
1. Create 3 different projects
2. Submit file URLs for all 3 simultaneously
3. Observe all download progress pages

**Expected Results:**
- ✅ All downloads proceed in parallel
- ✅ Each project shows independent progress
- ✅ No interference between downloads
- ✅ Celery worker handles concurrent tasks

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 7.4: Very Long Filenames
**Feature:** Filename handling
**Priority:** Low

**Steps:**
1. Upload file with very long name (>200 characters)
2. Submit URL with long filename in path

**Expected Results:**
- ✅ Filename truncated or handled gracefully
- ✅ No database errors (varchar limits respected)
- ✅ UI displays filename without breaking layout

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 7.5: Special Characters in Filenames
**Feature:** Filename sanitization
**Priority:** Medium

**Steps:**
1. Upload file with special characters: `test file (v2) [final].gds`
2. Submit URL with special characters

**Expected Results:**
- ✅ Special characters handled correctly
- ✅ No path traversal vulnerabilities
- ✅ Filename displayed correctly in UI

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

## Section 8: User Interface & Usability

### Test 8.1: Responsive Design - Mobile View
**Feature:** Mobile responsiveness
**Priority:** Medium

**Steps:**
1. Resize browser to mobile width (375px)
2. Navigate through: login, project list, project detail, file upload
3. Observe layout

**Expected Results:**
- ✅ Navigation collapses to hamburger menu
- ✅ Tables and forms remain usable
- ✅ Buttons accessible
- ✅ No horizontal scrolling required
- ✅ Text readable without zooming

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 8.2: Browser Compatibility
**Feature:** Cross-browser support
**Priority:** Medium

**Browsers to Test:**
- [ ] Chrome/Chromium
- [ ] Firefox
- [ ] Safari (if available)
- [ ] Edge

**Expected Results:**
- ✅ All features work in all browsers
- ✅ UI renders correctly
- ✅ No console errors
- ✅ Forms submit properly

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 8.3: Form Validation Feedback
**Feature:** User-friendly error messages
**Priority:** High

**Steps:**
1. Submit empty project form
2. Submit invalid URL
3. Submit file without selecting file
4. Observe error messages

**Expected Results:**
- ✅ Errors displayed near relevant fields
- ✅ Error messages clear and actionable
- ✅ Red/warning styling on error fields
- ✅ No page refresh required to see errors
- ✅ Previous valid inputs preserved

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 8.4: Success Message Visibility
**Feature:** User feedback
**Priority:** Medium

**Steps:**
1. Perform various successful actions:
   - Create project
   - Update project
   - Delete project
   - Upload file
2. Observe success messages

**Expected Results:**
- ✅ Success messages clearly visible (green/positive styling)
- ✅ Messages appear at top of page or near action
- ✅ Messages auto-dismiss after few seconds OR have close button
- ✅ Messages don't obscure important content

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

## Section 9: Performance & Load

### Test 9.1: Large Project List Performance
**Feature:** Pagination and performance
**Priority:** Low

**Steps:**
1. Create 25+ projects
2. Navigate to project list
3. Observe page load time and behavior

**Expected Results:**
- ✅ Page loads in < 2 seconds
- ✅ Pagination appears (20 projects per page)
- ✅ Pagination controls work correctly
- ✅ Smooth navigation between pages

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 9.2: Progress Polling Performance
**Feature:** AJAX polling efficiency
**Priority:** Medium

**Steps:**
1. Start file download
2. Keep project detail page open
3. Open browser developer tools → Network tab
4. Observe AJAX requests

**Expected Results:**
- ✅ Progress endpoint polled every 3 seconds
- ✅ No excessive requests (e.g., not every 100ms)
- ✅ Polling stops when download completes
- ✅ No memory leaks (page can stay open for extended period)

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

## Section 10: Data Integrity

### Test 10.1: Project Data Persistence
**Feature:** Database reliability
**Priority:** Critical

**Steps:**
1. Create project with description and file
2. Restart Django server (Ctrl+C, then `make runserver`)
3. Navigate to project detail page

**Expected Results:**
- ✅ All project data intact
- ✅ File information preserved
- ✅ Timestamps accurate
- ✅ No data loss

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 10.2: File Hash Consistency
**Feature:** Hash calculation accuracy
**Priority:** High

**Steps:**
1. Upload file with known hash
2. Calculate hash externally: `md5sum file.gds`
3. Compare with hash stored in database

**Expected Results:**
- ✅ Calculated hash matches external tool
- ✅ MD5 is 32 hexadecimal characters
- ✅ SHA1 is 40 hexadecimal characters
- ✅ Hashes stored in lowercase

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

## Section 11: Background Task System

### Test 11.1: Celery Worker Availability
**Feature:** Background job processing
**Priority:** Critical

**Steps:**
1. Stop Celery worker
2. Submit file URL
3. Observe behavior
4. Start Celery worker

**Expected Results:**
- ✅ File submission succeeds even without worker
- ✅ Status shows "Download Pending"
- ✅ When worker starts, download begins automatically
- ✅ No error messages about worker unavailability

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

### Test 11.2: Task Retry Mechanism
**Feature:** Automatic retry on failure
**Priority:** High

**Steps:**
1. Submit URL to unreliable server (intermittent failures)
2. Monitor Celery logs
3. Observe retry behavior

**Expected Results:**
- ✅ Task retries up to 5 times
- ✅ Exponential backoff applied (60s → 120s → 240s → 480s → 960s)
- ✅ Error message after max retries
- ✅ Retry count visible

**Actual Results:** ___________________
**Status:** PASS / FAIL / SKIP
**Notes:** ___________________

---

## Defect Report Template

### Defect #: ___________

**Test Case:** ___________________
**Severity:** Critical / High / Medium / Low
**Priority:** P1 / P2 / P3

**Steps to Reproduce:**
1.
2.
3.

**Expected Result:**


**Actual Result:**


**Screenshots/Logs:**


**Environment:**
- Browser: ___________________
- OS: ___________________
- Server version: ___________________

**Notes:**


---

## Test Summary Report

**Total Test Cases:** 50+
**Executed:** _____ / 50+
**Passed:** _____
**Failed:** _____
**Skipped:** _____
**Pass Rate:** _____%

### Critical Issues Found:
1.
2.
3.

### High Priority Issues:
1.
2.
3.

### Medium/Low Issues:
1.
2.
3.

### Recommendations:


### Sign-off:

Tester: _____________________
Date: _____________________
Signature: _____________________

Technical Lead: _____________________
Date: _____________________
Signature: _____________________

---

## Appendix A: Test Data Generation

### Generate Test GDS File (Linux/Mac)
```bash
# Create dummy GDS file for testing
dd if=/dev/urandom of=test.gds bs=1M count=5

# Calculate hashes
md5sum test.gds
sha1sum test.gds
```

### GitHub Test File Setup
1. Create public GitHub repository
2. Upload GDS file to repository
3. Navigate to file in GitHub UI
4. Click "Raw" button
5. Copy URL for testing

---

## Appendix B: Common Issues & Solutions

### Issue: Celery worker not processing tasks
**Solution:**
```bash
# Check worker status
celery -A config inspect active

# Restart worker
# Terminal: Ctrl+C, then make celery
```

### Issue: Database locked errors
**Solution:**
```bash
# Stop all Django/Celery processes
# Restart Django server first, then Celery
```

### Issue: File download stuck at 0%
**Solution:**
1. Check Celery worker is running
2. Check internet connectivity
3. Verify URL is accessible
4. Check Celery logs for errors

### Issue: Progress bar not updating
**Solution:**
1. Check browser console for JavaScript errors
2. Verify AJAX endpoint accessible
3. Hard refresh page (Ctrl+Shift+R)

---

## Appendix C: Accessibility Testing

### Keyboard Navigation
- [ ] Tab through all forms
- [ ] Submit forms with Enter key
- [ ] Navigate with arrow keys where applicable
- [ ] Access all buttons without mouse

### Screen Reader
- [ ] Test with screen reader (NVDA/JAWS/VoiceOver)
- [ ] All images have alt text
- [ ] Form labels properly associated
- [ ] Error messages announced

### Color Contrast
- [ ] Text readable against background
- [ ] Color not sole means of conveying information
- [ ] Links distinguishable from text

---

**End of Test Plan**
