# Quick Manual Test Checklist - Wafer.space Platform

**Quick Reference for Smoke Testing**
**Time Required:** ~15 minutes
**Use Case:** Pre-deployment verification, quick regression testing

---

## Prerequisites
```bash
# Start services
make runserver  # Terminal 1
make celery     # Terminal 2
```

---

## ✅ Smoke Test Checklist (15 minutes)

### 1. Authentication (2 minutes)
- [ ] Sign up new user works
- [ ] GitHub OAuth login works
- [ ] Logout works

### 2. Project CRUD (3 minutes)
- [ ] Create project
- [ ] View project list
- [ ] View project detail
- [ ] Edit project
- [ ] Delete project

### 3. File Upload (3 minutes)
- [ ] Upload local file (< 10MB)
- [ ] File appears in project detail
- [ ] File size shown correctly

### 4. File URL Download (5 minutes)
- [ ] Submit GitHub URL: `https://github.com/django/django/blob/main/README.rst`
- [ ] See URL rewriting message
- [ ] Progress bar appears
- [ ] Download completes
- [ ] File marked as completed

### 5. Security (2 minutes)
- [ ] Private IP rejected: `http://192.168.1.1/test.gds`
- [ ] Localhost rejected: `http://localhost/test.gds`
- [ ] Error messages clear

---

## ⚡ Critical Path Test (5 minutes)

**End-to-end happy path:**

1. [ ] Sign up → Create project → Upload file → View file details
2. Expected: < 5 minutes total, no errors

---

## 🔍 Regression Test Areas

### After Code Changes to:

**Models (`models.py`):**
- [ ] Run: Test 2.1 (Create project)
- [ ] Run: Test 4.1 (Upload file)
- [ ] Run: Test 10.1 (Data persistence)

**Views (`views.py`):**
- [ ] Run: Section 2 (All CRUD operations)
- [ ] Run: Section 6 (Access control)

**Tasks (`tasks.py`):**
- [ ] Run: Test 3.1 (URL download)
- [ ] Run: Test 3.2 (Progress tracking)
- [ ] Run: Test 11.2 (Retry mechanism)

**Security (`security.py`):**
- [ ] Run: Tests 3.4, 3.5, 3.6 (All security tests)

**Forms (`forms.py`):**
- [ ] Run: Test 8.3 (Form validation)
- [ ] Run: Test 4.4 (Invalid file extension)

---

## 🚨 Pre-Production Checklist

**Before deploying to production:**

- [ ] All 5 smoke tests pass
- [ ] No console errors in browser
- [ ] Celery worker running
- [ ] Database migrations applied
- [ ] File uploads working
- [ ] URL downloads working
- [ ] Authentication working
- [ ] Security validation working

**Critical Security Checks:**
- [ ] Private IP URLs rejected
- [ ] Only user's own projects visible
- [ ] File size limit enforced (100GB)

---

## 🐛 Quick Bug Check

**Common issues to verify are fixed:**

- [ ] No 500 errors on any page
- [ ] No broken images/CSS
- [ ] Forms submit without JavaScript errors
- [ ] Progress bars update correctly
- [ ] Success messages display
- [ ] Error messages helpful

---

## 📊 Performance Spot Check

- [ ] Project list loads < 2 seconds (even with 20+ projects)
- [ ] File upload feels instant (< 5MB files)
- [ ] Progress polling doesn't freeze page
- [ ] No memory leaks (page usable after 5+ minutes)

---

## Test Data Quick Setup

```bash
# Create test file
dd if=/dev/urandom of=test.gds bs=1M count=5

# Get hashes
md5sum test.gds
sha1sum test.gds
```

**Test URLs:**
```
Valid GitHub: https://github.com/django/django/blob/main/README.rst
Private IP: http://192.168.1.1/test.gds
Localhost: http://localhost/test.gds
```

---

## When Tests Fail

### File download stuck?
1. Check: `celery -A config inspect active`
2. Restart: Ctrl+C both terminals, restart

### Database errors?
1. Stop all processes
2. `make migrate`
3. Restart

### Page won't load?
1. Check: `make runserver` output
2. Check: Port 8081 not in use
3. Hard refresh: Ctrl+Shift+R

---

## Test Status Record

**Date:** ___________
**Tester:** ___________
**Result:** PASS / FAIL
**Issues Found:** ___________

---

**Full Test Plan:** See `docs/manual_test_plan.md` for comprehensive testing
