# Documentation Index

This directory contains documentation for the wafer.space platform.

---

## Getting Started

| Document | Description |
|----------|-------------|
| [Developer Onboarding](developer_onboarding.md) | Setup guide for new developers |
| [OAuth Setup](oauth_setup.md) | Configuring OAuth providers (GitHub, Google, etc.) |
| [Troubleshooting](troubleshooting.md) | Common issues and solutions |

---

## Architecture

| Document | Description |
|----------|-------------|
| [Celery Architecture](celery_architecture.md) | Task queue design, queue naming, state machine |
| [Celery Tasks Reference](celery_tasks_reference.md) | Complete listing of all Celery tasks |
| [Settings Catalog](settings.md) | Django settings across environments |
| [systemd Services](systemd-services.md) | Production worker configuration and security |

---

## Features

| Document | Description |
|----------|-------------|
| [Manufacturability Checking](manufacturability_checking.md) | Docker-based design rule checking workflow |
| [GDS Downloads](gds_downloads.md) | File download functionality |
| [Download Retry Architecture](download-retry-architecture.md) | Retry logic and error handling for downloads |
| [Download State Verification](download-state-verification.md) | File hash verification during downloads |
| [Admin Project Access](admin_project_access.md) | Staff access to user projects with audit logging |

---

## Deployment

| Document | Description |
|----------|-------------|
| [Production Deployment](production_deployment.md) | Deploying to Debian servers |
| [systemd Services](systemd-services.md) | Service configuration for production |
| [OAuth Secret Rotation](oauth_secret_rotation.md) | Rotating OAuth credentials |

---

## Testing

| Document | Description |
|----------|-------------|
| [Manual Test Plan](manual_test_plan.md) | Comprehensive manual testing checklist |
| [Manual Test Quick Checklist](manual_test_quick_checklist.md) | Quick reference for common tests |

---

## Other Resources

- [README.md](../README.md) - Project overview and quick start
- [CLAUDE.md](../CLAUDE.md) - Development guidelines and conventions
- [deployment/README.md](../deployment/README.md) - Deployment scripts overview
- [tests/browser/README.md](../tests/browser/README.md) - Browser testing guide
