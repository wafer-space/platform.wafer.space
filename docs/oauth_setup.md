# OAuth Provider Setup Guide

This guide walks through setting up OAuth applications for social authentication in the wafer.space platform.

## Table of Contents
- [GitHub OAuth Setup](#github-oauth-setup)
- [Google OAuth Setup](#google-oauth-setup)
- [GitLab OAuth Setup](#gitlab-oauth-setup)
- [LinkedIn OAuth Setup](#linkedin-oauth-setup)
- [Environment Configuration](#environment-configuration)
- [Testing OAuth Integration](#testing-oauth-integration)
- [Troubleshooting](#troubleshooting)

## GitHub OAuth Setup

### Creating a GitHub OAuth App for wafer-space Organization

1. **Navigate to wafer-space Organization Settings**
   - Go to https://github.com/wafer-space
   - Click on "Settings" tab in the organization navigation
   - In the left sidebar, scroll down to "Developer settings"
   - Click on "OAuth Apps"
   - Click "New OAuth App"

   **Note**: You must be an organization owner or have appropriate permissions to create OAuth apps for the organization.

2. **Configure the OAuth Application**
   - **Application name**: `wafer.space Platform Development` (for development) or `wafer.space Platform` (for production)
   - **Homepage URL**:
     - Development: `http://localhost:8000`
     - Production: `https://platform.wafer.space` (or your production domain)
   - **Application description**: "OAuth authentication for wafer.space low-cost silicon manufacturing platform"
   - **Authorization callback URL**:
     - Development: `http://localhost:8000/accounts/github/login/callback/`
     - Production: `https://platform.wafer.space/accounts/github/login/callback/`

   **Production Setup**: Create separate OAuth apps for development and production environments with different callback URLs.

3. **Configure Additional Settings**
   - **Enable Device Flow**: **Leave UNCHECKED** (not needed for web authentication)
     - Device Flow is only needed for authenticating devices without browsers (like CLI tools, IoT devices)
     - The wafer.space platform uses standard web OAuth flow through browsers
     - Enabling it unnecessarily expands the attack surface

4. **Register the Application**
   - Click "Register application"
   - You'll be redirected to your app's settings page
   - The app will be owned by the wafer-space organization

5. **Obtain Credentials**
   - **Client ID**: Displayed on the app page (public, safe to commit in settings)
   - **Client Secret**: Click "Generate a new client secret" (keep this secret and never commit to version control!)
   - Save both values securely

6. **Organization App Management**
   - The OAuth app will appear in the wafer-space organization's OAuth Apps list
   - Organization owners can manage, modify, or revoke the app
   - The app will have access to public information of organization members (if they authorize it)

### Environment Variables

Add these to your `.env` file:

```bash
# GitHub OAuth credentials for wafer-space organization
# Client IDs are configured in Django settings:
# - Development: Ov23liLB7RRJUzku13dU (in settings/base.py)
# - Production: Ov23linEhI33aev2uGSU (in settings/production.py)
#
# You only need to set the secrets:
GITHUB_CLIENT_SECRET=your_github_client_secret_here

# Optionally override the Client ID if using a different app:
# GITHUB_CLIENT_ID=your_custom_client_id_here
```

**Organization Best Practices:**
- **Use a shared password manager** (1Password, Bitwarden, etc.) for OAuth secrets
- **Document app ownership**: Record which team member created each OAuth app
- **Implement secret rotation**: Rotate secrets every 90 days or when team members leave
- **Separate environments**: Use different OAuth apps for development, staging, and production
- **Audit regularly**: Review OAuth app access and remove unused applications
- **Never commit secrets**: Client secrets must never be committed to version control

### 🔐 Security Model

**What's Safe to Commit:**
- ✅ Client IDs (public identifiers, already configured in Django settings)
- ✅ Configuration files with placeholders
- ✅ Documentation and setup scripts

**What Must Stay Secret:**
- 🚫 Client secrets (stored in password manager only)
- 🚫 Production credentials
- 🚫 Personal OAuth app credentials

**Developer Access Options:**
1. **Team members**: Get shared development secret from password manager
2. **External contributors**: Create personal OAuth apps for testing
3. **Backend developers**: Work without OAuth (limited features, full testing)

For detailed setup instructions, see [Developer Onboarding Guide](developer_onboarding.md).

### Organization OAuth Benefits

When users authenticate with GitHub OAuth from the wafer-space organization app:
- Organization members will see a trusted application badge during OAuth consent
- The organization can maintain centralized control over the OAuth application
- Organization owners can revoke access for all users if needed
- Users will see "wafer-space" as the application owner, building trust
- Access logs and analytics are available to organization owners

### Scopes

The GitHub provider is configured to request the following scope:
- `user:email` - Read access to user email addresses

**Note**: The application only requests minimal scopes required for authentication. Organization membership information is not accessed unless explicitly configured.

## Google OAuth Setup

### Creating a Google OAuth Application

1. **Navigate to Google Cloud Console**
   - Go to https://console.cloud.google.com/
   - Sign in with your Google account

2. **Create or Select a Project**
   - Click on the project dropdown at the top
   - Either select an existing project or click "New Project"
   - For new project: Enter project name (e.g., "wafer-space-dev")
   - Click "Create"

3. **Enable Required APIs**
   - In the left sidebar, go to "APIs & Services" > "Library"
   - Search for "Google+ API" and enable it
   - Alternatively, search for "Identity and Access Management (IAM) API" and enable it

4. **Configure OAuth Consent Screen**
   - Go to "APIs & Services" > "OAuth consent screen"
   - Choose "External" user type (unless you have Google Workspace)
   - Fill in required fields:
     - **App name**: `wafer.space Development` (or appropriate name)
     - **User support email**: Your email address
     - **Developer contact information**: Your email address
   - Add scopes: `../auth/userinfo.email` and `../auth/userinfo.profile`
   - Click "Save and Continue" through the steps

5. **Create OAuth 2.0 Credentials**
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Choose "Web application" as application type
   - Configure the application:
     - **Name**: `wafer.space OAuth Client`
     - **Authorized JavaScript origins**: `http://localhost:8000`
     - **Authorized redirect URIs**: `http://localhost:8000/accounts/google/login/callback/`

   For production:
   - **Authorized JavaScript origins**: `https://your-domain.com`
   - **Authorized redirect URIs**: `https://your-domain.com/accounts/google/login/callback/`

6. **Obtain Credentials**
   - Click "Create"
   - Copy the **Client ID** and **Client Secret** from the popup
   - Save both values securely

### Environment Variables

Add these to your `.env` file:

```bash
GOOGLE_CLIENT_ID=your_google_client_id_here.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_google_client_secret_here
```

### Scopes

The Google provider is configured to request the following scopes:
- `profile` - Basic profile information
- `email` - Email address

### Important Notes

- Google OAuth requires HTTPS in production
- The consent screen must be configured before OAuth will work
- Google has strict policies about redirect URI matching
- Client IDs ending in `.apps.googleusercontent.com` are normal

## GitLab OAuth Setup

### Creating a GitLab OAuth Application

1. **Navigate to GitLab Applications**
   - Go to https://gitlab.com/-/profile/applications (for GitLab.com)
   - Or go to your self-hosted GitLab instance: `https://your-gitlab-instance.com/-/profile/applications`
   - Sign in with your GitLab account

2. **Create New Application**
   - Click "Add new application"
   - Fill in the application details:
     - **Name**: `wafer.space Development` (or appropriate name)
     - **Redirect URI**: `http://localhost:8000/accounts/gitlab/login/callback/`
     - **Scopes**: Select the following checkboxes:
       - `read_user` - Read access to user profile information
       - `email` - Read access to user email addresses

   For production:
   - **Redirect URI**: `https://your-domain.com/accounts/gitlab/login/callback/`

3. **Submit the Application**
   - Click "Save application"
   - You'll be redirected to a page showing your application details

4. **Obtain Credentials**
   - **Application ID**: Displayed on the application page (public)
   - **Secret**: Displayed on the application page (keep this secret!)
   - Save both values securely

### Environment Variables

Add these to your `.env` file:

```bash
GITLAB_CLIENT_ID=your_gitlab_application_id_here
GITLAB_CLIENT_SECRET=your_gitlab_application_secret_here
```

### Scopes

The GitLab provider is configured to request the following scopes:
- `read_user` - Read access to user profile information
- `email` - Read access to user email addresses

### Important Notes

- GitLab OAuth works with both GitLab.com and self-hosted GitLab instances
- For self-hosted GitLab, you may need to configure the provider URL in Django settings
- GitLab requires exact redirect URI matching
- The "email" scope is essential for account linking functionality

## LinkedIn OAuth Setup

*Coming soon - will be added when implementing LinkedIn provider*

## Environment Configuration

### Development Setup

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Fill in the OAuth credentials for each provider you want to use.

3. Ensure Django is configured to read the `.env` file by setting:
   ```bash
   export DJANGO_READ_DOT_ENV_FILE=True
   ```

### Production Setup

In production, set environment variables directly in your hosting environment (e.g., Heroku, AWS, etc.) rather than using a `.env` file.

## Testing OAuth Integration

### Prerequisites

1. **Environment Setup**
   ```bash
   # Copy environment file if not already done
   cp .env.example .env

   # Edit .env and add your OAuth credentials
   # At minimum, add GitHub credentials for testing
   ```

2. **Database Setup**
   ```bash
   # Run migrations
   uv run python manage.py migrate

   # Create a superuser (optional)
   uv run python manage.py createsuperuser
   ```

### Local Testing

1. **Start the development server:**
   ```bash
   uv run python manage.py runserver
   ```

2. **Test UI Elements:**
   - Navigate to http://localhost:8000/accounts/login/
   - Verify all social provider buttons are displayed (GitHub, Google, GitLab, LinkedIn)
   - Verify traditional email/password form is present below social buttons
   - Check responsive design by resizing browser window

3. **Test OAuth Flow (with configured provider):**
   - Click on a configured provider button (e.g., GitHub)
   - You should be redirected to the provider's OAuth page
   - Authorize the application
   - You should be redirected back and logged in

### Automated Testing

**🏆 Excellent Testing Strategy**: This project uses the **gold standard** approach for OAuth testing.

1. **Run Unit Tests (No Secrets Required):**
   ```bash
   # Run all authentication tests - work without real OAuth credentials
   uv run pytest wafer_space/users/tests/test_social_auth_*.py -v

   # Test specific providers
   uv run pytest wafer_space/users/tests/test_social_auth_github.py -v
   uv run pytest wafer_space/users/tests/test_social_auth_google.py -v
   ```

2. **Testing Approach Benefits:**
   - ✅ **Fast execution** - no network dependencies
   - ✅ **Deterministic results** - no external service failures
   - ✅ **Security conscious** - no real credentials in CI
   - ✅ **Complete coverage** - tests configuration, UI, and business logic

3. **What Gets Tested:**
   - **Configuration tests**: Provider settings, scopes, callback URLs
   - **UI tests**: Button presence, styling, responsive design
   - **Flow tests**: OAuth redirect logic, state parameters (mocked)
   - **Security tests**: CSRF protection, email verification settings

4. **CI/CD Integration:**
   ```bash
   # All tests pass in CI without any OAuth secrets
   make test                     # Unit tests
   make test-browser-headless    # Browser tests
   make lint-fix                # Code quality
   ```

**🚫 Why We Don't Use Real OAuth in CI:**
- OAuth requires user interaction (consent screens)
- External dependencies make tests unreliable
- Real secrets in CI increase attack surface
- Mock-based testing is faster and more secure

### Browser Testing

1. **Run Headless Browser Tests:**
   ```bash
   # Run all browser tests including OAuth UI tests
   make test-browser-headless

   # Run only GitHub auth browser tests
   uv run pytest tests/browser/test_github_auth_flow.py -v
   ```

2. **Expected Browser Test Results:**
   - All UI element tests should PASS
   - Button visibility tests should PASS
   - Responsive design tests should PASS

### Manual Verification Checklist

Before closing issue #4, verify the following:

#### UI Verification
- [ ] Login page at `/accounts/login/` displays all 4 social provider buttons
- [ ] Signup page at `/accounts/signup/` displays all 4 social provider buttons
- [ ] Social buttons have appropriate icons (GitHub, Google, GitLab, LinkedIn)
- [ ] "OR" divider appears between social buttons and email form
- [ ] Traditional email/password form is still functional
- [ ] Responsive design works on mobile viewport (buttons stack vertically)

#### OAuth Flow Verification (requires configured provider)

**GitHub:**
- [ ] GitHub OAuth redirects to GitHub.com for authorization
- [ ] Successful GitHub auth creates new user account
- [ ] Existing users can link GitHub to their account
- [ ] Email from GitHub is used for account (if same email exists, accounts link)

**Google:**
- [ ] Google OAuth redirects to accounts.google.com for authorization
- [ ] Google consent screen shows correct app name and permissions
- [ ] Successful Google auth creates new user account
- [ ] Existing users can link Google to their account
- [ ] Email from Google is used for account (if same email exists, accounts link)
- [ ] Google profile information is correctly imported

**GitLab:**
- [ ] GitLab OAuth redirects to gitlab.com/oauth/authorize for authorization
- [ ] GitLab consent screen shows correct app name and permissions (read_user, email)
- [ ] Successful GitLab auth creates new user account
- [ ] Existing users can link GitLab to their account
- [ ] Email from GitLab is used for account (if same email exists, accounts link)
- [ ] GitLab profile information is correctly imported
- [ ] Self-hosted GitLab instances work with custom SERVER_URL configuration

#### Configuration Verification
- [ ] Environment variables are read correctly from `.env`
- [ ] Missing OAuth credentials don't break the application
- [ ] All 4 providers appear in Django admin at `/admin/socialaccount/socialapp/`

#### Testing Verification

**GitHub Tests:**
- [ ] Unit tests for configuration pass: `uv run pytest wafer_space/users/tests/test_social_auth_github.py::TestGitHubProviderConfiguration -v`
- [ ] GitHub browser UI tests pass: `uv run pytest tests/browser/test_github_auth_flow.py::TestGitHubAuthenticationFlow -v`

**Google Tests:**
- [ ] Unit tests for configuration pass: `uv run pytest wafer_space/users/tests/test_social_auth_google.py::TestGoogleProviderConfiguration -v`
- [ ] Google browser UI tests pass: `uv run pytest tests/browser/test_github_auth_flow.py::TestGoogleAuthenticationFlow -v`

**GitLab Tests:**
- [ ] Unit tests for configuration pass: `uv run pytest wafer_space/users/tests/test_social_auth_gitlab.py::TestGitLabProviderConfiguration -v`
- [ ] GitLab browser UI tests pass: `uv run pytest tests/browser/test_github_auth_flow.py::TestGitLabAuthenticationFlow -v`

**Overall Tests:**
- [ ] All provider configurations tested: `uv run pytest wafer_space/users/tests/test_social_auth_*.py::*Configuration -v`

### Production Deployment Notes

Before deploying to production:

1. **Create OAuth Apps** for production domain (not localhost)
2. **Update callback URLs** to use production domain
3. **Set environment variables** in production environment
4. **Test OAuth flow** with production URLs
5. **Enable HTTPS** (required by most OAuth providers)
6. **Review security settings** in Django settings

### GitHub Actions for Deployment (Not Testing)

**✅ Use GitHub Actions secrets for deployment:**
```yaml
# .github/workflows/deploy.yml
- name: Deploy to production
  env:
    GITHUB_CLIENT_SECRET: ${{ secrets.GITHUB_CLIENT_SECRET_PROD }}
    GOOGLE_CLIENT_SECRET: ${{ secrets.GOOGLE_CLIENT_SECRET_PROD }}
  run: |
    # Deploy with real production secrets
    ./deploy.sh
```

**❌ Don't use GitHub Actions secrets for OAuth testing:**
- Tests should work without real credentials (current approach)
- OAuth flows can't be automated in CI (require user interaction)
- Mock-based testing is more reliable and secure

**GitHub Actions Secret Management:**
```bash
# Set production secrets (organization owners only)
gh secret set GITHUB_CLIENT_SECRET_PROD --body="actual_secret_here"
gh secret set GOOGLE_CLIENT_SECRET_PROD --body="actual_secret_here"

# Use environment protection rules for additional security
# Require approval for production deployments
```

## Troubleshooting

### Common Issues

#### "Redirect URI mismatch" Error
- **Problem**: The callback URL in your OAuth app doesn't match the one being used
- **Solution**:
  - Check that your OAuth app's callback URL exactly matches the one in your Django settings
  - For local development, ensure you're using `localhost:8000` not `127.0.0.1:8000` (or vice versa)
  - Include the trailing slash: `/accounts/github/login/callback/`

#### "Client ID or Secret not found" Error
- **Problem**: Environment variables are not being loaded
- **Solution**:
  - Verify `.env` file exists and contains the credentials
  - Ensure `DJANGO_READ_DOT_ENV_FILE=True` is set
  - Restart the Django development server after changing environment variables

#### Social Account Not Linking to Existing User
- **Problem**: User with same email exists but accounts don't link
- **Solution**:
  - Check `SOCIALACCOUNT_AUTO_SIGNUP = True` in settings
  - Verify `SOCIALACCOUNT_EMAIL_VERIFICATION = "none"` for trusted providers
  - Ensure the provider is configured with `"VERIFIED_EMAIL": True`

#### 500 Error During OAuth Callback
- **Problem**: Server error when returning from OAuth provider
- **Solution**:
  - Check Django logs for detailed error message
  - Verify all required provider settings are configured
  - Ensure database migrations are up to date: `uv run python manage.py migrate`

### Debug Mode

To enable detailed OAuth debugging:

1. Set Django debug mode:
   ```python
   DEBUG = True  # In settings/local.py
   ```

2. Check the Django debug toolbar for OAuth flow details

3. Review server logs for detailed error messages

### Getting Help

If you encounter issues not covered here:
1. Check the [django-allauth documentation](https://docs.allauth.org/)
2. Review the GitHub issue #4 for implementation details
3. Create a new issue with:
   - Error message
   - Steps to reproduce
   - Environment details (OS, Python version, etc.)