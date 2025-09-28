# Developer Onboarding Guide

This guide helps new developers on the wafer-space team get their local development environment set up securely and efficiently.

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/wafer-space/platform.wafer.space.git
cd platform.wafer.space

# 2. Run the setup script
python scripts/dev_setup.py

# 3. Install dependencies
uv sync

# 4. Run migrations
uv run python manage.py migrate

# 5. Start development
make runserver
```

## OAuth Secrets Management

### 🔐 Security Model

**Client IDs**: Public, safe to commit (already configured in Django settings)
**Client Secrets**: Private, shared by organization owners when needed

### 🏢 For Team Members

1. **Ask @mithro or organization owners** for the development OAuth secret
2. **Add the secret** to your `.env` file:
   ```bash
   GITHUB_CLIENT_SECRET=your_secret_here
   ```
3. **Keep it confidential** - never commit this file to git

### 👤 For External Contributors / Personal Development

You have several options:

#### Option 1: Create Your Own OAuth App (Recommended)
```bash
# 1. Go to GitHub Settings > Developer settings > OAuth Apps
# 2. Click "New OAuth App"
# 3. Configure:
#    - Application name: "wafer.space Development (YourName)"
#    - Homepage URL: http://localhost:8000
#    - Callback URL: http://localhost:8000/accounts/github/login/callback/
# 4. Copy Client ID and Secret to your .env:
GITHUB_CLIENT_ID=your_personal_client_id
GITHUB_CLIENT_SECRET=your_personal_client_secret
```

#### Option 2: Work Without OAuth (Limited Features)
```bash
# Skip OAuth setup in dev_setup.py
# Some features won't work, but core development is possible
# All tests will still pass
```

#### Option 3: Mock OAuth for Testing
```bash
# Use the existing test suite which mocks OAuth flows
# Perfect for testing authentication logic without real credentials
uv run pytest wafer_space/users/tests/test_social_auth_*.py
```

## Development Workflow Options

### 🎯 Full Feature Development (OAuth Required)
```bash
# Set up OAuth secrets (team password manager or personal app)
GITHUB_CLIENT_SECRET=your_secret_here

# Test the full authentication flow
make runserver
# Visit http://localhost:8081/accounts/login/
# Click "Sign in with GitHub" to test OAuth
```

### ⚡ Backend Development (OAuth Optional)
```bash
# Work without OAuth secrets
# Focus on business logic, database models, API endpoints
# Use Django admin for user management: /admin/
```

### 🧪 Test-Driven Development (No OAuth Needed)
```bash
# All tests work without real OAuth credentials
make test                        # Unit tests
make test-browser-headless       # Browser UI tests

# Tests cover:
# - OAuth configuration validation
# - UI element presence and styling
# - Authentication flow logic (mocked)
# - Security settings verification
```

## Security Guidelines

### ✅ What's Safe to Commit
- Client IDs (public identifiers)
- Configuration files with placeholder values
- Test files with mock credentials
- Documentation and setup scripts

### ❌ Never Commit
- Client secrets (even for development)
- Real user data or tokens
- Production credentials
- Personal OAuth app credentials

### 🔄 Secret Rotation
- **Development**: Rotate when team members leave
- **Production**: Rotate every 90 days or after security incidents
- **Testing**: Use mocks, no real secrets needed

## Troubleshooting

### OAuth Button Not Appearing
```bash
# Check if secret is configured
grep GITHUB_CLIENT_SECRET .env

# Verify OAuth app configuration
uv run python manage.py shell
>>> from django.conf import settings
>>> settings.SOCIALACCOUNT_PROVIDERS['github']['APP']['client_id']
'Ov23liLB7RRJUzku13dU'  # Should show the development Client ID
```

### "Redirect URI Mismatch" Error
```bash
# Ensure your OAuth app callback URL is exactly:
http://localhost:8000/accounts/github/login/callback/

# Note: Use localhost, not 127.0.0.1
# Note: Include the trailing slash
```

### Tests Failing
```bash
# OAuth-related tests should work without real credentials
uv run pytest wafer_space/users/tests/test_social_auth_github.py -v

# If tests fail, check:
# 1. Virtual environment is activated
# 2. Dependencies are installed: uv sync
# 3. Database is migrated: uv run python manage.py migrate
```

## Development Environment Matrix

| Scenario | OAuth Setup | Features Available | Testing Capability |
|----------|-------------|-------------------|-------------------|
| **Team Member** | Shared secret from organization owners | Full OAuth flow | Complete |
| **External Contributor** | Personal GitHub OAuth app | Full OAuth flow | Complete |
| **Backend Focus** | Skip OAuth setup | Core features only | Unit tests only |
| **CI/CD Pipeline** | No real secrets (mocked) | N/A | Full test suite |

## Getting Help

### 📚 Documentation
- [OAuth Setup Guide](oauth_setup.md) - Detailed OAuth configuration
- [CLAUDE.md](../CLAUDE.md) - Development commands and workflows
- [Testing Guide](../tests/browser/README.md) - Browser test instructions

### 💬 Communication
- **Team Chat**: Ask questions about password manager access
- **GitHub Issues**: Report bugs or request features
- **Code Reviews**: Get help with OAuth integration

### 🔧 Common Commands
```bash
# Development server
make runserver

# Run tests
make test                        # Unit tests
make test-browser-headless       # Browser tests
make lint-fix                   # Fix code style

# Database operations
make migrate
make createsuperuser
```

## Security Contacts

For security-related questions or to report vulnerabilities:
- **Internal**: Contact team leads via secure channels
- **External**: Create a private security advisory on GitHub
- **Urgent**: Follow the security policy in the repository

---

💡 **Remember**: The goal is secure, productive development. Choose the approach that best fits your role and the features you're working on.