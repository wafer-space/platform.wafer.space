# OAuth Provider Setup Guide

This guide walks through setting up OAuth applications for social authentication in the wafer.space platform.

## Quick Reference - wafer-space OAuth Applications

| | **GitHub** | **Google** | **GitLab** | **Discord** | **LinkedIn** |
|---|---|---|---|---|---|
| **Development Client ID** | `Ov23liLB7RRJUzku13dU` | `62545893239-jiesk1vfk22j87cth4ukq4alluc3nqhc.apps.googleusercontent.com` | `2a29dee626b3c8b544f6f2c3a8042f912130bd040f4d3c60ef0e5864a4962aaa` | `1426055950221054052` | `86j973nx41hlk7` |
| **Production Client ID** | `Ov23linEhI33aev2uGSU` | `62545893239-pgg1lcg28u9suivjh4nso9t8mev5qua2.apps.googleusercontent.com` | `f0fde384db4cd0fe11041488a6b87e9d3d20223385b78d1ba1ed4045fbea6c16` | `1426065281138167841` | `86q1gs3uqhpqt1` |
| **Client Secrets** | Env var required | Env var required | Env var required | ✅ Pre-configured | ✅ Pre-configured |
| **Management URL** | [github.com/wafer-space](https://github.com/wafer-space) | [console.cloud.google.com](https://console.cloud.google.com/apis/credentials) | [gitlab.com/groups/wafer-space](https://gitlab.com/groups/wafer-space/-/settings/applications) | [discord.com/developers](https://discord.com/developers/applications) | [linkedin.com/developers](https://www.linkedin.com/developers/apps) |

### Configuration Notes

- ✅ **Client IDs** are configured in Django settings for all providers (safe to commit)
- 🔐 **Client Secrets** are managed via environment variables or pre-configured defaults
- 🌍 Both development and production environments are fully configured out of the box
- 📱 All OAuth apps are configured as "Confidential" for secure server-side web applications
- ⚡ **Zero-Setup Development**: Discord and LinkedIn include pre-configured secrets for instant testing
- 🔑 **GitHub, Google, GitLab**: Require environment variable for client secret only (Client IDs pre-configured)
- 🚀 **Quick Start**: Most developers can begin testing OAuth immediately with minimal configuration

## Table of Contents
- [GitHub OAuth Setup](#github-oauth-setup)
- [Google OAuth Setup](#google-oauth-setup)
- [GitLab OAuth Setup](#gitlab-oauth-setup)
- [Discord OAuth Setup](#discord-oauth-setup)
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
     - Development: `http://localhost:8081` (note: port 8081)
     - Production: `https://platform.wafer.space`
   - **Application description**: "OAuth authentication for wafer.space low-cost silicon manufacturing platform"
   - **Authorization callback URL**:
     - Development: `http://localhost:8081/accounts/github/login/callback/` (note: port 8081)
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

GitHub OAuth Client IDs are pre-configured in Django settings:

```bash
# GitHub OAuth credentials for wafer-space organization
# Client IDs are configured in Django settings:
# - Development: Ov23liLB7RRJUzku13dU (settings/base.py)
# - Production: Ov23linEhI33aev2uGSU (settings/production.py)
#
# You only need to set the secret in your .env file:
GITHUB_CLIENT_SECRET=your_github_client_secret_here

# Optionally override the Client ID if using a different app:
# GITHUB_CLIENT_ID=your_custom_client_id_here
```

**Organization Best Practices:**
- **Share secrets securely**: Organization owners share development secrets with team members via secure channels
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
- 🚫 Client secrets (shared securely by organization owners)
- 🚫 Production credentials
- 🚫 Personal OAuth app credentials

**Developer Access Options:**
1. **Team members**: Get shared development secret from organization owners
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

### Callback URL Reference

- **Development**: `http://localhost:8081/accounts/github/login/callback/`
- **Production**: `https://platform.wafer.space/accounts/github/login/callback/`

**Pattern**: `/accounts/github/login/callback/`

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
     - **App name**: `wafer.space Development` (for development) or `wafer.space Platform` (for production)
     - **User support email**: Your email address
     - **Developer contact information**: Your email address
   - Add scopes: `../auth/userinfo.email` and `../auth/userinfo.profile`
   - Click "Save and Continue" through the steps

   **Important**: Your OAuth consent screen will start in "Testing" mode, which restricts access to test users only.

   **For Development**:
   - Add test users in the "Test users" section if needed
   - Testing mode is fine for development and allows up to 100 test users

   **For Production**:
   - Go back to "OAuth consent screen" after creating credentials
   - Click "PUBLISH APP" to make the app available to all users
   - **Warning**: Publishing requires Google's review for sensitive scopes, but basic profile/email scopes are usually auto-approved
   - Once published, any user can authenticate with your app

5. **Create OAuth 2.0 Credentials**
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Choose "Web application" as application type
   - Configure the application:
     - **Name**: `wafer.space OAuth Client Development`
     - **Authorized JavaScript origins**: `http://localhost:8081`
     - **Authorized redirect URIs**: `http://localhost:8081/accounts/google/login/callback/`

   For production:
   - **Name**: `wafer.space OAuth Client Production`
   - **Authorized JavaScript origins**: `https://platform.wafer.space`
   - **Authorized redirect URIs**: `https://platform.wafer.space/accounts/google/login/callback/`

6. **Obtain Credentials**
   - Click "Create"
   - Copy the **Client ID** and **Client Secret** from the popup
   - Save both values securely

### Environment Variables

Google OAuth Client IDs are pre-configured in Django settings:

```bash
# Google OAuth credentials for wafer-space project
# Client IDs are configured in Django settings:
# - Development: 62545893239-jiesk1vfk22j87cth4ukq4alluc3nqhc.apps.googleusercontent.com (settings/base.py)
# - Production: 62545893239-pgg1lcg28u9suivjh4nso9t8mev5qua2.apps.googleusercontent.com (settings/production.py)
#
# You only need to set the secret in your .env file:
GOOGLE_CLIENT_SECRET=your_google_client_secret_here

# Optionally override the Client ID if using a different app:
# GOOGLE_CLIENT_ID=your_custom_client_id_here
```

### Scopes

The Google provider is configured to request the following scopes:
- `profile` - Basic profile information
- `email` - Email address

### Callback URL Reference

- **Development**: `http://localhost:8081/accounts/google/login/callback/`
- **Production**: `https://platform.wafer.space/accounts/google/login/callback/`

**Pattern**: `/accounts/google/login/callback/`

### Important Notes

- **HTTPS Requirement**: Google OAuth requires HTTPS in production environments
- **Consent Screen**: The OAuth consent screen must be configured before OAuth will work
- **Redirect URI Matching**: Google enforces strict redirect URI matching, including protocol and port
- **Client ID Format**: Client IDs ending in `.apps.googleusercontent.com` are normal and expected
- **Testing Mode**: New apps start in "Testing" mode with up to 100 test users; publish for production
- **Port Configuration**: Development uses port 8081 (not 8000) to match the project's `make runserver` configuration

## GitLab OAuth Setup

### Creating a GitLab OAuth Application for wafer-space Group

**wafer-space Group ID**: 116401955

#### Option 1: Group-owned Application (Recommended for Team)

1. **Navigate to wafer-space Group Applications**
   - Go to https://gitlab.com/groups/wafer-space/-/settings/applications
   - Or navigate to the wafer-space group on GitLab.com:
     - Visit https://gitlab.com/wafer-space
     - In the group sidebar, go to **Settings** → **Applications**
   - Sign in with your GitLab account (you must be a group member with appropriate permissions)

2. **Create New Group Application**
   - Click **"New application"**
   - Fill in the application details:
     - **Name**: `wafer.space Platform Development` (for development) or `wafer.space Platform` (for production)
     - **Redirect URI**:
       - Development: `http://localhost:8081/accounts/gitlab/login/callback/` (note: port 8081)
       - Production: `https://platform.wafer.space/accounts/gitlab/login/callback/`
     - **Confidential**: ✅ **YES, check this box**
       - **Required for server-side web applications** like Django
       - Confidential applications can securely store client secrets
       - Non-confidential apps are for mobile/single-page apps that can't store secrets
     - **Scopes**: Select the following checkboxes:
       - ✅ `read_user` - Read access to user profile information
       - ✅ `email` - Read access to user email addresses

   **Production Setup**: Create separate applications for development and production environments with different redirect URIs.

3. **Save the Application**
   - Click **"Save application"**
   - You'll be redirected to a page showing your application details
   - The application will be owned by the wafer-space group

4. **Obtain Credentials**
   - **Application ID**: Displayed on the application page (this is your Client ID - public, safe to share)
   - **Secret**: Displayed on the application page (this is your Client Secret - keep this secret!)
   - Save both values securely

#### Option 2: Personal Application (For External Contributors)

1. **Navigate to Personal Applications**
   - Go to https://gitlab.com/-/profile/applications
   - Sign in with your GitLab account

2. **Create New Application**
   - Click "Add new application"
   - Fill in the application details:
     - **Name**: `wafer.space Development (YourName)`
     - **Redirect URI**: `http://localhost:8081/accounts/gitlab/login/callback/`
     - **Confidential**: ✅ **YES, check this box** (required for web applications)
     - **Scopes**: Select the following checkboxes:
       - `read_user` - Read access to user profile information
       - `email` - Read access to user email addresses

3. **Submit the Application**
   - Click "Save application"
   - You'll be redirected to a page showing your application details

4. **Obtain Credentials**
   - **Application ID**: Displayed on the application page (public)
   - **Secret**: Displayed on the application page (keep this secret!)
   - Save both values securely

### Group Application Benefits

When using a Group-owned GitLab OAuth application:
- **Centralized management**: Group owners can manage the application for all team members
- **Consistent branding**: Users see "wafer-space" as the application owner during OAuth consent
- **Team access**: All group members can use the same OAuth configuration
- **Easier secret sharing**: Group owners can securely share the Client Secret with team members
- **Access control**: Group owners can revoke access for all users if needed

### Environment Variables

GitLab OAuth Client IDs are pre-configured in Django settings:

```bash
# GitLab OAuth credentials for wafer-space group (ID: 116401955)
# Client IDs are configured in Django settings:
# - Development: 2a29dee626b3c8b544f6f2c3a8042f912130bd040f4d3c60ef0e5864a4962aaa (settings/base.py)
# - Production: f0fde384db4cd0fe11041488a6b87e9d3d20223385b78d1ba1ed4045fbea6c16 (settings/production.py)
#
# You only need to set the secret in your .env file:
GITLAB_CLIENT_SECRET=your_gitlab_application_secret_here

# Optionally override the Client ID if using a different app:
# GITLAB_CLIENT_ID=your_custom_application_id_here
```

### Scopes

The GitLab provider is configured to request the following scopes:
- `read_user` - Read access to user profile information
- `email` - Read access to user email addresses

### Callback URL Reference

- **Development**: `http://localhost:8081/accounts/gitlab/login/callback/`
- **Production**: `https://platform.wafer.space/accounts/gitlab/login/callback/`

**Pattern**: `/accounts/gitlab/login/callback/`

### Important Notes

- **Confidential Applications**: Always check "Confidential" for server-side web applications like Django - this allows secure storage of client secrets on the server
- **Non-Confidential Applications**: Only use for mobile apps or single-page applications that cannot securely store secrets
- **Self-Hosted Support**: GitLab OAuth works with both GitLab.com and self-hosted GitLab instances
- **Custom Instances**: For self-hosted GitLab, configure the provider URL in Django settings
- **Redirect URI Matching**: GitLab requires exact redirect URI matching, including protocol, port, and trailing slash
- **Email Scope**: The "email" scope is essential for account linking functionality
- **Port Configuration**: Development uses port 8081 (not 8000) to match the project's `make runserver` configuration

## LinkedIn OAuth Setup

### Creating a LinkedIn OAuth Application

1. **Navigate to LinkedIn Developers Portal**
   - Go to https://www.linkedin.com/developers/apps
   - Sign in with your LinkedIn account
   - Click the **"Create app"** button

2. **Create New Application**
   - Fill in the required application details:
     - **App name**: `wafer.space Development` (for development) or `wafer.space Platform` (for production)
     - **LinkedIn Page**: You'll need to associate the app with a LinkedIn Company Page
       - If you don't have one, you can create a Company Page for wafer.space or use a personal page
       - For development/testing, you can use any page you have admin access to
     - **App logo**: Upload a logo (PNG or JPG, recommended 300x300px minimum)
     - **Legal agreement**: Check the box to agree to LinkedIn API Terms of Use
   - Click **"Create app"**

   **Note**: LinkedIn requires a Company Page association for all OAuth apps. For development purposes, you can use any page you have admin access to.

3. **Verify Your Application**
   - After creating the app, LinkedIn will show a verification page
   - Click **"Verify"** and follow the process (may require email verification)
   - You can proceed with configuration while verification is pending

4. **Configure OAuth 2.0 Redirect URLs**
   - In your app dashboard, click on the **"Auth"** tab
   - Scroll down to the **"OAuth 2.0 settings"** section
   - Under **"Redirect URLs"**, click **"Add redirect URL"**
   - Add your redirect URI:
     - Development: `http://localhost:8081/accounts/linkedin_oauth2/login/callback/`
     - Production: `https://platform.wafer.space/accounts/linkedin_oauth2/login/callback/`
   - Click **"Update"** to save

   **Important**: LinkedIn requires exact redirect URI matching, including protocol, port, path, and trailing slash.

5. **Request Required Scopes**
   - In the **"Products"** tab, request access to **"Sign In with LinkedIn using OpenID Connect"**
   - Click **"Request access"** (usually auto-approved for basic profile/email scopes)
   - Once approved, the following scopes will be available:
     - `openid` - OpenID Connect authentication
     - `profile` - Basic profile information
     - `email` - Email address

   **Note**: LinkedIn's OAuth API has migrated to OpenID Connect. The legacy scopes (`r_liteprofile`, `r_emailaddress`) are being phased out but are still configured in django-allauth for backwards compatibility.

6. **Obtain Credentials**
   - Go to the **"Auth"** tab
   - Find the **"Application credentials"** section
   - **Client ID**: Displayed directly (safe to commit in settings)
   - **Client Secret**: Click **"Show"** to reveal, then copy (keep this secret and never commit to version control!)
   - Save both values securely

### Environment Variables

LinkedIn OAuth credentials are fully pre-configured in Django settings:

```bash
# LinkedIn OAuth credentials for wafer-space apps
# Client IDs and Secrets are configured in Django settings:
# - Development: 86j973nx41hlk7 (settings/base.py) with included secret
# - Production: 86q1gs3uqhpqt1 (settings/production.py) with included secret
# - Works out of the box in both environments - no .env configuration needed!
#
# Optionally override if using a different app:
# LINKEDIN_CLIENT_ID=your_custom_client_id_here
# LINKEDIN_CLIENT_SECRET=your_custom_client_secret_here
```

### Scopes

The LinkedIn provider is configured to request the following scopes:

**Current Configuration (Legacy API v2)**:
- `r_liteprofile` - Basic profile information (first name, last name, profile picture)
- `r_emailaddress` - Primary email address for account linking

**Note on Scopes**: LinkedIn is transitioning to OpenID Connect. While the current django-allauth configuration uses legacy v2 scopes, new applications should request the "Sign In with LinkedIn using OpenID Connect" product, which provides equivalent access through the OpenID Connect protocol.

### Callback URL Reference

- **Development**: `http://localhost:8081/accounts/linkedin_oauth2/login/callback/`
- **Production**: `https://platform.wafer.space/accounts/linkedin_oauth2/login/callback/`

**Pattern**: `/accounts/linkedin_oauth2/login/callback/`

**Note**: The provider name is `linkedin_oauth2` (not just `linkedin`) - this distinguishes it from the older LinkedIn OAuth 1.0 provider.

### Important Notes

- **Company Page Requirement**: LinkedIn requires all OAuth apps to be associated with a Company Page - for development, you can use any page you have admin access to
- **Verification Process**: LinkedIn may require email verification or additional steps before your app can be used in production
- **Redirect URI Matching**: LinkedIn enforces strict redirect URI matching - ensure the redirect URI matches exactly, including protocol, port, and trailing slash
- **HTTPS Requirement**: Production environments must use HTTPS - HTTP is only allowed for localhost development
- **Rate Limiting**: LinkedIn has rate limits on API calls - for authentication this is typically not an issue, but be aware for high-traffic applications
- **Scope Migration**: LinkedIn is transitioning from v2 API to OpenID Connect - new apps should use "Sign In with LinkedIn using OpenID Connect" product for future compatibility
- **Testing**: During development, you can test with your own LinkedIn account - once verified and approved, any LinkedIn user can authenticate
- **Port Configuration**: Development uses port 8081 (not 8000) to match the project's `make runserver` configuration
- **Zero Setup**: LinkedIn credentials are pre-configured in both development and production for instant testing

## Discord OAuth Setup

### Creating a Discord OAuth Application

1. **Navigate to Discord Developer Portal**
   - Go to https://discord.com/developers/applications
   - Sign in with your Discord account

2. **Create New Application**
   - Click **"New Application"** button in the top right
   - Enter application name (e.g., `wafer.space Development` or `wafer.space Platform` for production)
   - Accept the Developer Terms of Service and Developer Policy
   - Click **"Create"**

3. **Configure OAuth2 Redirect URIs**
   - In the left sidebar, click on **"OAuth2"**
   - Scroll down to the **"Redirects"** section
   - Click **"Add Redirect"**
   - Add your redirect URI:
     - Development: `http://localhost:8081/accounts/discord/login/callback/`
     - Production: `https://platform.wafer.space/accounts/discord/login/callback/`
   - Click **"Save Changes"**

   **Important**: Discord requires exact redirect URI matching, including the trailing slash.

4. **Obtain Credentials**
   - Go to **"OAuth2"** section in the left sidebar (or **"General Information"**)
   - **Client ID**: Copy the "CLIENT ID" shown (also called "APPLICATION ID" in General Information)
   - **Client Secret**: Click **"Reset Secret"** button, then click **"Yes, do it!"** to confirm
   - Copy the newly generated secret immediately - it will only be shown once!
   - Save both values securely

   **Note**: The Client Secret is only shown once when generated. If you lose it, you must reset it and update your `.env` file.

### Environment Variables

Discord OAuth credentials are fully pre-configured in Django settings:

```bash
# Discord OAuth credentials for wafer-space apps
# Client IDs and Secrets are configured in Django settings:
# - Development: 1426055950221054052 (settings/base.py) with included secret
# - Production: 1426065281138167841 (settings/production.py) with included secret
# - Works out of the box in both environments - no .env configuration needed!
#
# Optionally override if using a different app:
# DISCORD_CLIENT_ID=your_custom_client_id_here
# DISCORD_CLIENT_SECRET=your_custom_client_secret_here
```

### Scopes

The Discord provider is configured to request the following scopes:
- `identify` - Required to fetch user ID and basic profile information (Discord requirement)
- `email` - Read access to user email address (required for account linking)

### Callback URL Reference

- **Development**: `http://localhost:8081/accounts/discord/login/callback/`
- **Production**: `https://platform.wafer.space/accounts/discord/login/callback/`

**Pattern**: `/accounts/discord/login/callback/`

### Important Notes

- **Application vs Bot**: Discord applications can be both OAuth apps and bots - for wafer.space, we **only** use OAuth authentication for user login - you do **not** need to add a bot or configure bot permissions
- **Redirect URI Matching**: Discord requires exact redirect URI matching, including protocol (`http://` vs `https://`), port, and trailing slash
- **Client Secret Security**: The client secret is only shown once when generated - if lost, reset it in the Discord Developer Portal and update your environment variables
- **Email Verification**: Users must have a verified email on Discord - the `VERIFIED_EMAIL: True` setting ensures only verified Discord accounts can authenticate
- **Port Configuration**: Development uses port 8081 (not 8000) to match the project's `make runserver` configuration
- **Zero Setup**: Discord credentials are pre-configured in both development and production for instant testing

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
   make runserver
   ```

2. **Test UI Elements:**
   - Navigate to http://localhost:8081/accounts/login/
   - Verify all social provider buttons are displayed (GitHub, Google, GitLab, Discord, LinkedIn)
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
  - For local development, ensure you're using `localhost:8081` not `127.0.0.1:8081` (or vice versa)
  - Verify you're using port 8081 (the project's configured port, not Django's default 8000)
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

#### Google OAuth "Access Restricted to Test Users" Warning
- **Problem**: Google OAuth shows "OAuth access is restricted to the test users listed on your OAuth consent screen"
- **Solution**:
  - **For Development**: Add your email to the "Test users" list in OAuth consent screen settings
  - **For Production**:
    1. Go to Google Cloud Console > APIs & Services > OAuth consent screen
    2. Click "PUBLISH APP" to make the app available to all users
    3. Submit for verification if using sensitive scopes (basic profile/email usually auto-approved)
  - **Alternative for Development**: Keep in testing mode and add specific test users as needed

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

## Security and Maintenance

### Secret Rotation

OAuth secrets should be rotated regularly to maintain security:

- **Production secrets**: Every 90 days (recommended)
- **Development secrets**: When team members leave or every 180 days
- **Emergency rotation**: Immediately if secrets are leaked or compromised

**For detailed rotation instructions**, see [OAuth Secret Rotation Guide](oauth_secret_rotation.md)

The rotation guide covers:
- Step-by-step rotation process for each OAuth provider
- Backup and rollback procedures
- Verification testing
- Emergency rotation procedures
- Security best practices

### Getting Help

If you encounter issues not covered here:
1. Check the [django-allauth documentation](https://docs.allauth.org/)
2. Review the GitHub issue #4 for implementation details
3. Create a new issue with:
   - Error message
   - Steps to reproduce
   - Environment details (OS, Python version, etc.)