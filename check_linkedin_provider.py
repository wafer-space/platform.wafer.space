#!/usr/bin/env python
"""
Diagnostic script to check LinkedIn provider configuration in production.

Run with: DJANGO_SETTINGS_MODULE=config.settings.production uv run python check_linkedin_provider.py
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django.setup()

from allauth.socialaccount.models import SocialApp
from allauth.socialaccount import providers
from django.conf import settings

print("=" * 80)
print("LinkedIn Provider Diagnostic")
print("=" * 80)

# Check settings configuration
print("\n1. Settings Configuration:")
print("-" * 80)
oidc_config = settings.SOCIALACCOUNT_PROVIDERS.get("openid_connect", {})
linkedin_apps = [
    app for app in oidc_config.get("APPS", [])
    if app.get("provider_id") == "linkedin"
]
print(f"OpenID Connect APPS with provider_id='linkedin': {len(linkedin_apps)}")
if linkedin_apps:
    for app in linkedin_apps:
        print(f"  - Name: {app.get('name')}")
        print(f"  - Provider ID: {app.get('provider_id')}")
        print(f"  - Client ID: {app.get('client_id')}")
        print(f"  - Has Secret: {'Yes' if app.get('secret') else 'No'}")

# Check database SocialApp objects
print("\n2. Database SocialApp Objects:")
print("-" * 80)
social_apps = SocialApp.objects.all()
print(f"Total SocialApp objects: {social_apps.count()}")
for app in social_apps:
    print(f"  - Provider: {app.provider}, Name: {app.name}, ID: {app.id}")

# Check specifically for LinkedIn-related apps
linkedin_social_apps = SocialApp.objects.filter(
    provider__icontains="linkedin"
)
print(f"\nLinkedIn-related SocialApp objects: {linkedin_social_apps.count()}")
for app in linkedin_social_apps:
    print(f"  - Provider: {app.provider}, Name: {app.name}, ID: {app.id}")

# Check provider registry
print("\n3. Provider Registry:")
print("-" * 80)
registry = providers.registry
linkedin_providers = [p for p in registry.get_list() if "linkedin" in p.id.lower()]
print(f"Registered LinkedIn providers: {len(linkedin_providers)}")
for provider in linkedin_providers:
    print(f"  - ID: {provider.id}, Name: {provider.name}")

# Check what providers are available in templates
print("\n4. Template Context (what templates see):")
print("-" * 80)
from allauth.socialaccount.templatetags.socialaccount import get_providers
template_providers = get_providers()
print(f"Total providers available in templates: {len(template_providers)}")
for provider in template_providers:
    is_linkedin = "linkedin" in provider.id.lower()
    marker = " ← LINKEDIN" if is_linkedin else ""
    print(f"  - ID: '{provider.id}', Name: '{provider.name}'{marker}")

print("\n" + "=" * 80)
print("Diagnosis:")
print("=" * 80)

# Determine the issue
if linkedin_social_apps.exists():
    print("⚠️  ISSUE FOUND: Database has old LinkedIn SocialApp objects")
    print("\nThese database objects may override settings-based configuration.")
    print("\nRecommended fix:")
    print("  1. Delete old SocialApp objects:")
    for app in linkedin_social_apps:
        print(f"     SocialApp.objects.filter(id={app.id}).delete()  # {app.provider}")
    print("  2. Restart gunicorn")
    print("  3. Clear browser cache and reload")
elif not linkedin_apps:
    print("⚠️  ISSUE FOUND: No LinkedIn OpenID Connect configuration in settings")
    print("\nCheck that config/settings/production.py has:")
    print('  "openid_connect": {"APPS": [{"provider_id": "linkedin", ...}]}')
elif not template_providers:
    print("⚠️  ISSUE FOUND: No providers available in templates")
else:
    linkedin_in_templates = [p for p in template_providers if p.id == "linkedin"]
    if linkedin_in_templates:
        print("✅ Configuration looks correct!")
        print(f"   Provider ID in templates: '{linkedin_in_templates[0].id}'")
        print("\nIf button still shows incorrectly, try:")
        print("  1. python manage.py collectstatic --noinput")
        print("  2. Restart gunicorn")
        print("  3. Clear browser cache")
    else:
        print("⚠️  Provider ID mismatch detected")
        print(f"\nProviders in templates: {[p.id for p in template_providers]}")
        print("Expected: 'linkedin'")

print("=" * 80)
