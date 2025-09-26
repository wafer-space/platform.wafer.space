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

*Coming soon - will be added when implementing Google provider*

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

### Local Testing

1. Start the development server:
   ```bash
   uv run python manage.py runserver
   ```

2. Navigate to http://localhost:8000/accounts/login/

3. You should see social login buttons for configured providers

4. Click on a provider button to test the OAuth flow

### Automated Testing

Run the authentication tests:
```bash
# Run all authentication tests
uv run pytest wafer_space/users/tests/test_social_auth_*.py

# Run provider-specific tests
uv run pytest wafer_space/users/tests/test_social_auth_github.py
```

### Browser Testing

Run headless browser tests:
```bash
make test-browser-headless
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