"""
Update checker for TheLogger.

Checks GitHub releases API for new versions.
"""

import asyncio
import json
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional

from .logging_utils import get_module_logger

logger = get_module_logger(__name__)

GITHUB_REPO = "redscientific/RS_Logger2"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"


@dataclass
class UpdateInfo:
    """Information about an available update."""
    current_version: str
    latest_version: str
    download_url: str
    release_notes: str = ""


def parse_version(version_str: str) -> tuple:
    """Parse version string into comparable tuple.

    Handles versions like "2.0.0", "v2.0.0", "2.0.0-beta".
    """
    # Strip leading 'v' if present
    version = version_str.lstrip('v')

    # Split off any pre-release suffix
    if '-' in version:
        version = version.split('-')[0]

    # Parse into tuple of integers
    try:
        parts = tuple(int(p) for p in version.split('.'))
        # Pad to at least 3 parts
        while len(parts) < 3:
            parts = parts + (0,)
        return parts
    except ValueError:
        return (0, 0, 0)


def is_newer_version(current: str, latest: str) -> bool:
    """Check if latest version is newer than current."""
    return parse_version(latest) > parse_version(current)


async def check_for_updates(current_version: str) -> Optional[UpdateInfo]:
    """Check GitHub for available updates.

    Args:
        current_version: The currently running version string.

    Returns:
        UpdateInfo if an update is available, None otherwise.
        Returns None silently on any error (network, parsing, etc).
    """
    try:
        # Run the blocking HTTP request in a thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _fetch_latest_release)

        if result is None:
            return None

        latest_version, release_notes, assets = result

        if not is_newer_version(current_version, latest_version):
            logger.debug("No update available (current: %s, latest: %s)",
                        current_version, latest_version)
            return None

        logger.info("Update available: %s -> %s", current_version, latest_version)

        return UpdateInfo(
            current_version=current_version,
            latest_version=latest_version,
            download_url=RELEASES_PAGE_URL,
            release_notes=release_notes
        )

    except Exception as e:
        logger.debug("Update check failed: %s", e)
        return None


def _fetch_latest_release() -> Optional[tuple]:
    """Fetch latest release info from GitHub API.

    Returns:
        Tuple of (version, release_notes, assets) or None on error.
    """
    try:
        request = urllib.request.Request(
            RELEASES_API_URL,
            headers={
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'RPi-Logger-Update-Checker'
            }
        )

        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))

        tag_name = data.get('tag_name', '')
        body = data.get('body', '')
        assets = data.get('assets', [])

        if not tag_name:
            return None

        return (tag_name, body, assets)

    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        logger.debug("Failed to fetch release info: %s", e)
        return None
    except Exception as e:
        logger.debug("Unexpected error fetching release: %s", e)
        return None
