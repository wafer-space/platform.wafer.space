# 🚨 CRITICAL WARNING 🚨

## NEVER RUN BROWSER TESTS WITH PYTEST DIRECTLY

**Any command containing `pytest tests/browser/` WILL OPEN VISIBLE BROWSERS!**

### ❌ FORBIDDEN COMMANDS ❌
```bash
pytest tests/browser/
uv run pytest tests/browser/
python -m pytest tests/browser/
pytest tests/browser/test_github_auth_flow.py
```

### ✅ ONLY USE THESE COMMANDS ✅
```bash
make test-browser-headless           # ALWAYS USE THIS
make test-browser-firefox-headless   # Alternative
make test-browser-parallel           # Parallel execution
```

## Rule: Check Every Test Command
Before running ANY test command:
1. Does the path contain "browser"?
2. If YES → STOP and use `make test-browser-headless`
3. If NO → Proceed with pytest

**NO EXCEPTIONS!**