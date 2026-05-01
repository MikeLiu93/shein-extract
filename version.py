"""
Single source of truth for the app version.
Bump this here, rebuild, tag git as v{VERSION}, push, create GitHub release.
update_check.py compares this against GitHub's latest release tag_name.
"""

VERSION = "3.5.0"
