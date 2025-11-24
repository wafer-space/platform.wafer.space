# Wafer.space Platform Makefile
# Development environment setup and task automation

# Variables
PYTHON := python3
UV := uv
VENV := .venv
PROJECT_NAME := wafer_space
MANAGE := $(UV) run python manage.py
CELERY := $(UV) run celery

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

.PHONY: help
help: ## Show this help message
	@echo "$(BLUE)Wafer.space Platform Development Commands$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "$(GREEN)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Usage: make [target]$(NC)"

# ==================== Setup ====================

.PHONY: install
install: ## Install uv package manager
	@echo "$(BLUE)Installing uv package manager...$(NC)"
	@curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "$(GREEN)✓ uv installed successfully$(NC)"

.PHONY: venv
venv: ## Create virtual environment and install dependencies
	@echo "$(BLUE)Creating virtual environment with uv...$(NC)"
	@$(UV) venv
	@echo "$(BLUE)Installing dependencies...$(NC)"
	@$(UV) sync
	@echo "$(GREEN)✓ Virtual environment created and dependencies installed$(NC)"

.PHONY: dev-install
dev-install: venv ## Install development dependencies
	@echo "$(BLUE)Installing development dependencies...$(NC)"
	@$(UV) sync --dev
	@echo "$(GREEN)✓ Development dependencies installed$(NC)"

.PHONY: clean-venv
clean-venv: ## Remove virtual environment
	@echo "$(YELLOW)Removing virtual environment...$(NC)"
	@rm -rf $(VENV)
	@echo "$(GREEN)✓ Virtual environment removed$(NC)"

.PHONY: reinstall
reinstall: clean-venv venv ## Reinstall virtual environment from scratch

# ==================== Database ====================

.PHONY: migrate
migrate: ## Run database migrations
	@echo "$(BLUE)Running database migrations...$(NC)"
	@$(MANAGE) migrate
	@echo "$(GREEN)✓ Migrations applied$(NC)"

.PHONY: makemigrations
makemigrations: ## Create new database migrations
	@echo "$(BLUE)Creating database migrations...$(NC)"
	@$(MANAGE) makemigrations
	@echo "$(GREEN)✓ Migrations created$(NC)"

.PHONY: db-reset
db-reset: ## Reset database (WARNING: Deletes all data!)
	@echo "$(RED)WARNING: This will delete all data!$(NC)"
	@echo "Press Ctrl+C to cancel, or wait 3 seconds to continue..."
	@sleep 3
	@rm -f db.sqlite3
	@$(MANAGE) migrate
	@echo "$(GREEN)✓ Database reset complete$(NC)"

.PHONY: createsuperuser
createsuperuser: ## Create Django superuser
	@echo "$(BLUE)Creating superuser...$(NC)"
	@$(MANAGE) createsuperuser

.PHONY: collectstatic
collectstatic: ## Collect static files
	@echo "$(BLUE)Collecting static files...$(NC)"
	@mkdir -p staticfiles
	@$(MANAGE) collectstatic --noinput
	@echo "$(GREEN)✓ Static files collected$(NC)"

# ==================== Testing ====================

.PHONY: test
test: ## Run all tests (unit + browser, all headless by default)
	@echo "$(BLUE)Running all tests...$(NC)"
	@$(UV) run pytest
	@echo "$(GREEN)✓ Tests complete$(NC)"

.PHONY: test-verbose
test-verbose: ## Run tests with verbose output
	@echo "$(BLUE)Running tests with verbose output...$(NC)"
	@$(UV) run pytest -vv

.PHONY: test-fast
test-fast: ## Run tests in parallel (requires pytest-xdist)
	@echo "$(BLUE)Running tests in parallel...$(NC)"
	@$(UV) run pytest -n auto

.PHONY: test-app
test-app: ## Run tests for specific app (use APP=appname)
	@if [ -z "$(APP)" ]; then \
		echo "$(RED)Please specify an app: make test-app APP=referrals$(NC)"; \
		exit 1; \
	fi
	@echo "$(BLUE)Running tests for $(APP)...$(NC)"
	@$(UV) run pytest wafer_space/$(APP)/

.PHONY: test-coverage
test-coverage: ## Run tests with coverage report
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	@$(UV) run coverage run -m pytest
	@$(UV) run coverage report
	@echo "$(GREEN)✓ Coverage report generated$(NC)"

.PHONY: test-coverage-html
test-coverage-html: ## Generate HTML coverage report
	@echo "$(BLUE)Running tests with HTML coverage report...$(NC)"
	@$(UV) run coverage run -m pytest
	@$(UV) run coverage html
	@echo "$(GREEN)✓ HTML coverage report generated in htmlcov/$(NC)"
	@echo "$(YELLOW)Open htmlcov/index.html in your browser$(NC)"

.PHONY: test-failed
test-failed: ## Run only previously failed tests
	@echo "$(BLUE)Running previously failed tests...$(NC)"
	@$(UV) run pytest --lf

.PHONY: test-marker
test-marker: ## Run tests with specific marker (use MARKER=slow)
	@if [ -z "$(MARKER)" ]; then \
		echo "$(RED)Please specify a marker: make test-marker MARKER=slow$(NC)"; \
		exit 1; \
	fi
	@echo "$(BLUE)Running tests marked with $(MARKER)...$(NC)"
	@$(UV) run pytest -m $(MARKER)

# ==================== Browser Testing ====================

.PHONY: test-browser
test-browser: ## Run browser tests (headless by default, screenshots capture state)
	@echo "$(BLUE)Running browser tests in headless mode...$(NC)"
	@mkdir -p tests/browser/screenshots
	@$(UV) run pytest tests/browser/ --browser=chrome -v

.PHONY: test-browser-firefox
test-browser-firefox: ## Run browser tests with Firefox (headless)
	@echo "$(BLUE)Running browser tests with Firefox (headless)...$(NC)"
	@mkdir -p tests/browser/screenshots
	@$(UV) run pytest tests/browser/ --browser=firefox -v

.PHONY: test-browser-parallel
test-browser-parallel: ## Run browser tests in parallel (headless)
	@echo "$(BLUE)Running browser tests in parallel...$(NC)"
	@mkdir -p tests/browser/screenshots
	@$(UV) run pytest tests/browser/ --browser=chrome -n auto -v

.PHONY: test-manual
test-manual: ## Run manual/visual tests with VISIBLE browser (human debugging only)
	@if [ "$$CLAUDECODE" = "1" ]; then \
		echo "$(RED)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)"; \
		echo "$(RED)ERROR: Manual tests are BLOCKED in Claude Code$(NC)"; \
		echo "$(RED)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)"; \
		echo ""; \
		echo "$(YELLOW)Manual tests are for HUMAN visual debugging only.$(NC)"; \
		echo "$(YELLOW)They open visible browser windows and disturb the user.$(NC)"; \
		echo ""; \
		echo "$(BLUE)What you should do instead:$(NC)"; \
		echo "  make test                    # All tests (headless)"; \
		echo "  make test-browser            # Browser tests (headless)"; \
		echo ""; \
		echo "$(RED)Claude Code cannot run manual tests. This is not negotiable.$(NC)"; \
		echo ""; \
		exit 1; \
	fi
	@echo "$(YELLOW)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)"
	@echo "$(YELLOW)⚠️  MANUAL TEST MODE - VISIBLE BROWSERS WILL OPEN$(NC)"
	@echo "$(YELLOW)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)"
	@echo ""
	@echo "$(BLUE)Running manual tests with visible browser windows...$(NC)"
	@echo "$(BLUE)These tests are for visual debugging by humans only.$(NC)"
	@echo ""
	@mkdir -p tests/browser/screenshots
	@$(UV) run pytest -m manual --visible --browser=chrome -v -s

.PHONY: test-browser-mobile
test-browser-mobile: ## Run browser tests with mobile viewport (headless)
	@echo "$(BLUE)Running browser tests with mobile viewport...$(NC)"
	@mkdir -p tests/browser/screenshots
	@$(UV) run pytest tests/browser/ --browser=chrome --window-size=375,667 -v

.PHONY: test-browser-tablet
test-browser-tablet: ## Run browser tests with tablet viewport (headless)
	@echo "$(BLUE)Running browser tests with tablet viewport...$(NC)"
	@mkdir -p tests/browser/screenshots
	@$(UV) run pytest tests/browser/ --browser=chrome --window-size=768,1024 -v

.PHONY: test-browser-screenshots
test-browser-screenshots: ## Clean browser test screenshots
	@echo "$(BLUE)Cleaning browser test screenshots...$(NC)"
	@rm -rf tests/browser/screenshots/*
	@echo "$(GREEN)✓ Screenshots cleaned$(NC)"

# ==================== Code Quality ====================

.PHONY: lint
lint: ## Run code linting with ruff
	@echo "$(BLUE)Running ruff linter...$(NC)"
	@$(UV) run ruff check .
	@echo "$(GREEN)✓ Linting complete$(NC)"

.PHONY: lint-fix
lint-fix: ## Run ruff with auto-fix
	@echo "$(BLUE)Running ruff with auto-fix...$(NC)"
	@$(UV) run ruff check --fix .
	@$(UV) run ruff format .
	@echo "$(GREEN)✓ Linting and formatting complete$(NC)"

.PHONY: type-check
type-check: ## Run mypy type checking
	@echo "$(BLUE)Running mypy type checker...$(NC)"
	@$(UV) run mypy wafer_space
	@echo "$(GREEN)✓ Type checking complete$(NC)"

.PHONY: format
format: ## Format code with ruff
	@echo "$(BLUE)Formatting code...$(NC)"
	@$(UV) run ruff format .
	@echo "$(GREEN)✓ Code formatted$(NC)"

.PHONY: shellcheck
shellcheck: ## Run shellcheck on all shell scripts
	@echo "$(BLUE)Running shellcheck on shell scripts...$(NC)"
	@shellcheck deployment/scripts/*.sh deployment/systemd/install.sh deployment/nginx/install.sh scripts/*.sh
	@echo "$(GREEN)✓ Shellcheck complete$(NC)"

.PHONY: check-all
check-all: lint type-check test ## Run all checks (lint, type-check, tests)

# ==================== Development Server ====================

.PHONY: runserver
runserver: ## Run Django development server with Celery worker (via Honcho)
	@echo "$(BLUE)Starting development server and Celery worker...$(NC)"
	@echo "$(BLUE)Cleaning Celery Beat schedule database...$(NC)"
	@rm -f celerybeat-schedule celerybeat-schedule.db celerybeat-schedule.sqlite3 celerybeat-schedule.sqlite3-shm celerybeat-schedule.sqlite3-wal
	@$(UV) run honcho start

.PHONY: stop
stop: ## Stop all running dev servers (honcho, celery, django runserver)
	@echo "$(BLUE)Stopping development servers...$(NC)"
	@if pgrep -f "[h]oncho start" >/dev/null 2>&1; then \
		pgrep -f "[h]oncho start" | xargs kill -9 2>/dev/null; \
		echo "  $(GREEN)✓ Stopped honcho$(NC)"; \
	else \
		echo "  $(YELLOW)○ No honcho process found$(NC)"; \
	fi
	@if pgrep -f "[c]elery -A config worker" >/dev/null 2>&1; then \
		pgrep -f "[c]elery -A config worker" | xargs kill -9 2>/dev/null; \
		echo "  $(GREEN)✓ Stopped celery workers$(NC)"; \
	else \
		echo "  $(YELLOW)○ No celery workers found$(NC)"; \
	fi
	@if pgrep -f "[c]elery -A config beat" >/dev/null 2>&1; then \
		pgrep -f "[c]elery -A config beat" | xargs kill -9 2>/dev/null; \
		echo "  $(GREEN)✓ Stopped celery beat$(NC)"; \
	else \
		echo "  $(YELLOW)○ No celery beat found$(NC)"; \
	fi
	@if pgrep -f "[m]anage.py runserver" >/dev/null 2>&1; then \
		pgrep -f "[m]anage.py runserver" | xargs kill -9 2>/dev/null; \
		echo "  $(GREEN)✓ Stopped django runserver$(NC)"; \
	else \
		echo "  $(YELLOW)○ No django runserver found$(NC)"; \
	fi
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

.PHONY: shell
shell: ## Open Django shell
	@echo "$(BLUE)Opening Django shell...$(NC)"
	@$(MANAGE) shell

.PHONY: shell-plus
shell-plus: ## Open Django shell_plus (requires django-extensions)
	@echo "$(BLUE)Opening Django shell_plus...$(NC)"
	@$(MANAGE) shell_plus

# ==================== Celery ====================

.PHONY: celery
celery: ## Start Celery worker
	@echo "$(BLUE)Starting Celery worker...$(NC)"
	@$(CELERY) -A config worker --loglevel=info

.PHONY: celery-purge
celery-purge: ## Purge all Celery tasks
	@echo "$(YELLOW)Purging all Celery tasks...$(NC)"
	@$(CELERY) -A config purge
	@echo "$(GREEN)✓ Celery tasks purged$(NC)"

# ==================== Utilities ====================

.PHONY: clean
clean: ## Clean up Python cache files
	@echo "$(BLUE)Cleaning up Python cache files...$(NC)"
	@find . -type f -name "*.pyc" -delete
	@find . -type d -name "__pycache__" -delete
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".coverage" -delete
	@find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)✓ Cleanup complete$(NC)"

.PHONY: clean-all
clean-all: clean clean-venv ## Clean everything including virtual environment
	@echo "$(BLUE)Cleaning temporary files...$(NC)"
	@rm -rf tmp/
	@rm -f db.sqlite3
	@echo "$(GREEN)✓ Full cleanup complete$(NC)"

.PHONY: show-urls
show-urls: ## Show all URL patterns
	@echo "$(BLUE)URL patterns:$(NC)"
	@$(MANAGE) show_urls

.PHONY: check-deploy
check-deploy: ## Check deployment readiness
	@echo "$(BLUE)Checking deployment readiness...$(NC)"
	@$(MANAGE) check --deploy
	@echo "$(GREEN)✓ Deployment check complete$(NC)"

# ==================== CI/CD ====================

.PHONY: ci-test
ci-test: ## Run tests for CI/CD pipeline
	@echo "$(BLUE)Running CI tests...$(NC)"
	@$(UV) run pytest --tb=short --strict-markers -q

.PHONY: pre-commit
pre-commit: lint-fix test ## Run pre-commit checks
	@echo "$(BLUE)Running pre-commit checks...$(NC)"
	@$(UV) run pre-commit run --all-files
	@echo "$(GREEN)✓ Pre-commit checks complete$(NC)"

# ==================== Documentation ====================

.PHONY: docs
docs: ## Build documentation
	@echo "$(BLUE)Building documentation...$(NC)"
	@cd docs && make html
	@echo "$(GREEN)✓ Documentation built in docs/_build/html$(NC)"

.PHONY: docs-live
docs-live: ## Start live documentation server
	@echo "$(BLUE)Starting live documentation server...$(NC)"
	@cd docs && make livehtml

# ==================== Deployment ====================

.PHONY: restart
restart: ## Restart all services
	@echo "$(BLUE)Restarting all platform services...$(NC)"
	@deployment/scripts/restart.sh
	@echo "$(GREEN)✓ Services restarted$(NC)"

.PHONY: reset-logs
reset-logs: ## Reset/clear all log files (requires sudo)
	@echo "$(BLUE)Resetting application logs...$(NC)"
	@sudo deployment/scripts/reset-logs.sh
	@echo "$(GREEN)✓ Logs reset$(NC)"

# Default target
.DEFAULT_GOAL := help
