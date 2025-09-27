#!/bin/bash
# Safe test runner that prevents visible browser tests

set -e

# Function to check if command would run visible browser tests
check_browser_command() {
    local cmd="$1"

    if [[ "$cmd" == *"tests/browser"* && "$cmd" == *"pytest"* ]]; then
        echo "🚨 ERROR: Attempting to run visible browser tests!"
        echo "❌ FORBIDDEN: $cmd"
        echo "✅ USE INSTEAD: make test-browser-headless"
        echo ""
        echo "Browser tests MUST use make commands to run in headless mode."
        exit 1
    fi
}

# Check the provided command
if [ $# -eq 0 ]; then
    echo "Usage: $0 <test-command>"
    echo "Example: $0 'uv run pytest wafer_space/users/tests/'"
    echo ""
    echo "This script prevents accidentally running visible browser tests."
    exit 1
fi

COMMAND="$*"
check_browser_command "$COMMAND"

echo "✅ Safe to run: $COMMAND"
exec $COMMAND