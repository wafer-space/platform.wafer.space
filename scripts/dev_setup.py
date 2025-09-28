#!/usr/bin/env python3
"""
Development Environment Setup Script for wafer.space

This script helps new developers set up their local development environment
by guiding them through OAuth configuration.
"""

import os
import sys
from pathlib import Path


def main():
    """Guide developers through setting up their local environment."""

    print("🔧 wafer.space Development Environment Setup")
    print("=" * 50)

    # Check if we're in the right directory
    if not Path("manage.py").exists():
        print("❌ Error: Please run this script from the project root directory")
        sys.exit(1)

    # Check if .env already exists
    env_file = Path(".env")
    if env_file.exists():
        print("✅ .env file already exists")
        overwrite = input("Do you want to update OAuth configuration? (y/N): ")
        if overwrite.lower() != 'y':
            print("Setup cancelled.")
            return
    else:
        # Copy from example
        env_example = Path(".env.example")
        if env_example.exists():
            with open(env_example) as f:
                content = f.read()
            with open(env_file, 'w') as f:
                f.write(content)
            print("✅ Created .env file from .env.example")

    print("\n📋 OAuth Configuration Setup")
    print("-" * 30)

    print("""
🔐 GitHub OAuth Setup:

The GitHub Client ID is already configured in Django settings.
You need to obtain the Client Secret from the team's password manager.

📋 Steps:
1. Ask a team member for access to the shared password manager
2. Look for "wafer.space GitHub OAuth - Development Secret"
3. Copy the secret value
4. Paste it below when prompted

💡 Alternative: If you don't have access to secrets yet, you can:
   - Skip OAuth setup (some features won't work locally)
   - Set up your own GitHub OAuth app for testing
   - Work on features that don't require authentication
""")

    # Prompt for GitHub secret
    setup_oauth = input("\nDo you want to configure GitHub OAuth now? (y/N): ")

    if setup_oauth.lower() == 'y':
        secret = input("\nPaste the GitHub OAuth Client Secret: ").strip()

        if secret:
            # Update .env file
            update_env_var("GITHUB_CLIENT_SECRET", secret)
            print("✅ GitHub OAuth configured successfully!")
        else:
            print("⚠️  Skipped GitHub OAuth configuration")
    else:
        print("⚠️  Skipped OAuth setup - some features may not work locally")

    print(f"""
🎉 Setup Complete!

Next steps:
1. Install dependencies: uv sync
2. Run migrations: uv run python manage.py migrate
3. Create superuser: uv run python manage.py createsuperuser
4. Start development server: uv run python manage.py runserver

🧪 Test your setup:
- Visit http://localhost:8000/accounts/login/
- You should see GitHub OAuth button (if configured)
- All tests should pass: uv run pytest

📚 Documentation:
- OAuth setup: docs/oauth_setup.md
- Development guide: CLAUDE.md

💬 Need help? Ask in the team chat or create a GitHub issue.
""")


def update_env_var(key, value):
    """Update or add an environment variable in .env file."""
    env_file = Path(".env")

    if env_file.exists():
        lines = env_file.read_text().splitlines()
    else:
        lines = []

    # Find and update existing key or add new one
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            updated = True
            break

    if not updated:
        lines.append(f"{key}={value}")

    env_file.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()