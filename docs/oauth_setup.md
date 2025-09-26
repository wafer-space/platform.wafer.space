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

### Creating a GitHub OAuth App

1. **Navigate to GitHub Settings**
   - Go to https://github.com/settings/developers
   - Click on "OAuth Apps" in the left sidebar
   - Click "New OAuth App"

2. **Configure the OAuth Application**
   - **Application name**: `wafer.space Development` (or appropriate name)
   - **Homepage URL**: `http://localhost:8000`
   - **Application description**: (optional) "wafer.space development environment"
   - **Authorization callback URL**: `http://localhost:8000/accounts/github/login/callback/`

   For production:
   - **Homepage URL**: `https://your-domain.com`
   - **Authorization callback URL**: `https://your-domain.com/accounts/github/login/callback/`

3. **Register the Application**
   - Click "Register application"
   - You'll be redirected to your app's settings page

4. **Obtain Credentials**
   - **Client ID**: Displayed on the app page (public)
   - **Client Secret**: Click "Generate a new client secret" (keep this secret!)
   - Save both values securely

### Environment Variables

Add these to your `.env` file:

```bash
GITHUB_CLIENT_ID=your_github_client_id_here
GITHUB_CLIENT_SECRET=your_github_client_secret_here
```

### Scopes

The GitHub provider is configured to request the following scope:
- `user:email` - Read access to user email addresses

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

*Coming soon - will be added when implementing GitLab provider*

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

1. **Run Unit Tests:**
   ```bash
   # Run all authentication tests
   uv run pytest wafer_space/users/tests/test_social_auth_*.py -v

   # Run GitHub provider tests
   uv run pytest wafer_space/users/tests/test_social_auth_github.py -v

   # Run Google provider tests
   uv run pytest wafer_space/users/tests/test_social_auth_google.py -v
   ```

2. **Expected Test Results:**
   - **Configuration tests should PASS** (provider installed, scopes configured)
   - **OAuth flow tests may FAIL** without real credentials (expected behavior)
   - **Template tests may FAIL** without configured apps (expected in test environment)

   **Note**: Social provider buttons only appear when OAuth apps are properly configured with credentials or database objects.

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

**Overall Tests:**
- [ ] Both provider configurations tested: `uv run pytest wafer_space/users/tests/test_social_auth_*.py::*Configuration -v`

### Production Deployment Notes

Before deploying to production:

1. **Create OAuth Apps** for production domain (not localhost)
2. **Update callback URLs** to use production domain
3. **Set environment variables** in production environment
4. **Test OAuth flow** with production URLs
5. **Enable HTTPS** (required by most OAuth providers)
6. **Review security settings** in Django settings

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