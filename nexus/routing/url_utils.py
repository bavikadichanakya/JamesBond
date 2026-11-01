"""URL Normalization, Domain Validation, and Website Intent Recognition for NEXUS.

Provides strict, RFC-compliant URL normalization, domain validation,
prohibited scheme rejection, and dynamic website intent extraction from natural language.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, Optional, Set, Tuple

# Pre-approved desktop applications (to strictly distinguish apps from websites)
DEFAULT_APP_NAMES: Set[str] = {
    "chrome", "google chrome", "notepad", "calculator", "calc",
    "explorer", "windows explorer", "mspaint", "paint",
    "taskmgr", "task manager", "edge", "microsoft edge",
}

# Pre-approved user folders (to distinguish folders from websites)
DEFAULT_FOLDER_NAMES: Set[str] = {
    "downloads", "download", "documents", "document", "docs",
    "desktop", "workspace", "mixer", "pictures", "picture",
    "photos", "videos", "video", "music",
}

# Prohibited URL schemes that must NEVER be dispatched to the browser
PROHIBITED_SCHEMES: Set[str] = {
    "file", "javascript", "data", "powershell", "vbscript",
    "cmd", "about", "shell", "ftp", "ws", "wss", "local",
    "ms-settings", "reg",
}

# RFC 1035 / RFC 1123 compliant hostname label:
# 1-63 chars, alphanumeric or internal hyphen, cannot start or end with hyphen
LABEL_REGEX = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$")

# TLD: 2 to 63 alphabetic characters
TLD_REGEX = re.compile(r"^[a-zA-Z]{2,63}$")

# IPv4 regex
IPV4_REGEX = re.compile(
    r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)

# Domain detection pattern in natural language
DOMAIN_PATTERN = re.compile(
    r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,63}(?:/[^\s]*)?\b",
    re.IGNORECASE,
)

# Navigation verbs/prefixes
NAVIGATION_VERB_PATTERNS = [
    r"^open\s+(?:the\s+)?(?:website|site|url|webpage|page)\s+(.+)$",
    r"^launch\s+(?:the\s+)?(?:website|site|url|webpage|page)\s+(.+)$",
    r"^visit\s+(?:the\s+)?(?:website|site|url|webpage|page)\s+(.+)$",
    r"^browse\s+(?:to\s+)?(?:the\s+)?(?:website|site|url|webpage|page\s+)?(.+)$",
    r"^navigate\s+to\s+(?:the\s+)?(?:website|site|url|webpage|page\s+)?(.+)$",
    r"^go\s+to\s+(?:the\s+)?(?:website|site|url|webpage|page\s+)?(.+)$",
    r"^visit\s+(.+)$",
    r"^open\s+(.+)$",
    r"^launch\s+(.+)$",
]


def normalize_and_validate_url(raw_url: str) -> str:
    """Normalize and strictly validate a website URL.

    Guarantees:
    - Accepts HTTP and HTTPS only.
    - Rejects prohibited schemes (file:, javascript:, powershell:, data:, etc.).
    - Rejects malformed domains (adjacent dots, invalid labels, invalid TLDs).
    - Rejects arbitrary natural language text.
    - Preserves legitimate paths, query parameters, and fragments.
    - Normalizes scheme and hostname to lowercase.

    Args:
        raw_url: The raw URL or domain string to normalize and validate.

    Returns:
        The normalized, safe HTTPS or HTTP URL.

    Raises:
        ValueError: If the URL or domain is invalid, prohibited, or malformed.
    """
    if not raw_url or not isinstance(raw_url, str):
        raise ValueError("Parameter 'url' cannot be empty.")

    cleaned = raw_url.strip()
    if not cleaned:
        raise ValueError("Parameter 'url' cannot be empty.")

    # Strip wrapping quotes if any
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1].strip()

    # Reject control characters
    for ch in cleaned:
        if ord(ch) < 32 or ord(ch) == 127:
            raise ValueError("URL contains illegal control characters.")

    # Reject raw whitespace
    if any(c in cleaned for c in (" ", "\t", "\r", "\n")):
        raise ValueError(f"Invalid URL '{cleaned}': URLs cannot contain whitespace.")

    # Check for scheme prefix
    scheme_match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*):", cleaned)
    if scheme_match:
        scheme_prefix = scheme_match.group(1).lower()
        if scheme_prefix in PROHIBITED_SCHEMES:
            raise ValueError(
                f"Prohibited URL scheme '{scheme_prefix}:' in '{cleaned}'. "
                "Only 'http://' and 'https://' are supported."
            )
        if scheme_prefix not in ("http", "https"):
            raise ValueError(
                f"Unsupported URL scheme '{scheme_prefix}:' in '{cleaned}'. "
                "Only 'http://' and 'https://' are supported."
            )
        url_to_parse = cleaned
    else:
        # Check for local file path indicators
        if cleaned.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:[\\/]", cleaned):
            raise ValueError(
                f"Prohibited local file path '{cleaned}'. "
                "Only HTTP and HTTPS web URLs are permitted."
            )
        # Default scheme is HTTPS
        url_to_parse = "https://" + cleaned

    # Parse with urllib.parse.urlsplit
    try:
        parsed = urllib.parse.urlsplit(url_to_parse)
    except Exception as exc:
        raise ValueError(f"Malformed URL '{cleaned}': {str(exc)}") from exc

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme '{scheme}'. Only HTTP and HTTPS are permitted.")

    netloc = parsed.netloc
    if not netloc:
        raise ValueError(f"Malformed URL '{cleaned}': missing or empty hostname.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Malformed URL '{cleaned}': missing or empty domain.")

    hostname = hostname.lower()

    # Domain validation
    if ".." in hostname:
        raise ValueError(f"Malformed domain '{hostname}': contains adjacent dots.")

    if hostname == "localhost":
        pass
    elif IPV4_REGEX.match(hostname):
        pass
    else:
        labels = hostname.split(".")
        if len(labels) < 2:
            raise ValueError(
                f"Malformed domain '{hostname}': must contain at least one subdomain and a top-level domain."
            )
        for label in labels:
            if not label:
                raise ValueError(f"Malformed domain '{hostname}': empty label.")
            if len(label) > 63:
                raise ValueError(f"Malformed domain '{hostname}': label '{label}' exceeds 63 characters.")
            if not LABEL_REGEX.match(label):
                if label.startswith("-") or label.endswith("-"):
                    raise ValueError(f"Malformed domain '{hostname}': label '{label}' cannot begin or end with a hyphen.")
                raise ValueError(f"Malformed domain '{hostname}': label '{label}' contains invalid characters.")

        # Validate TLD
        tld = labels[-1]
        if not TLD_REGEX.match(tld):
            raise ValueError(
                f"Malformed domain '{hostname}': invalid top-level domain '{tld}'. TLD must be 2-63 alphabetic characters."
            )

    # Validate port if present
    port = parsed.port
    if port is not None:
        if not (1 <= port <= 65535):
            raise ValueError(f"Invalid port number {port} in URL '{cleaned}'. Must be between 1 and 65535.")
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            clean_netloc = hostname
        else:
            clean_netloc = f"{hostname}:{port}"
    else:
        clean_netloc = hostname

    # Reconstruct normalized URL
    normalized = urllib.parse.urlunsplit((
        scheme,
        clean_netloc,
        parsed.path,
        parsed.query,
        parsed.fragment,
    ))
    return normalized


def extract_website_target_from_query(
    query: str,
    app_allowlist: Optional[Set[str]] = None,
    approved_folders: Optional[Set[str]] = None,
) -> Optional[str]:
    """Extract and resolve a website target from natural language user input.

    Recognizes:
    - Direct URLs: https://github.com, http://example.com/test
    - Domains: instagram.com, youtube.com, reddit.com, myportfolio.io
    - Navigation directives: 'Open instagram.com', 'Visit github.com', 'Go to instagram.com'
    - Known/bare brand names: 'Open Instagram', 'Open YouTube'
    - Prohibited scheme triggers: 'open javascript:...', 'open file:...' (passed through for validation rejection)

    Distinguishes from:
    - Pre-approved applications ('Open Chrome', 'Open Calculator') -> returns None
    - Pre-approved user folders ('Open Downloads') -> returns None

    Args:
        query: Raw natural language prompt from the user.
        app_allowlist: Set of application identifiers to exclude.
        approved_folders: Set of folder names to exclude.

    Returns:
        The normalized URL string, or raw candidate target (if prohibited scheme),
        or None if not a website navigation request.
    """
    if not query or not isinstance(query, str):
        return None

    cleaned = query.strip()
    q_lower = cleaned.lower()

    apps = app_allowlist if app_allowlist is not None else DEFAULT_APP_NAMES
    folders = approved_folders if approved_folders is not None else DEFAULT_FOLDER_NAMES

    # 1. Check if query is an explicit HTTP/HTTPS or prohibited URL directly
    if re.match(r"^https?://", q_lower) or any(q_lower.startswith(f"{p}:") for p in PROHIBITED_SCHEMES):
        target = cleaned.split()[0] if " " in cleaned else cleaned
        try:
            return normalize_and_validate_url(target)
        except ValueError:
            # Return raw target so downstream handler rejects with specific error
            return target

    # 2. Check if query is a standalone domain
    words = cleaned.split()
    if len(words) == 1 and DOMAIN_PATTERN.match(words[0]):
        try:
            return normalize_and_validate_url(words[0])
        except ValueError:
            return words[0]

    # 3. Extract target using navigation verb patterns
    extracted_target: Optional[str] = None
    for pattern in NAVIGATION_VERB_PATTERNS:
        match = re.match(pattern, cleaned, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            # Strip trailing punctuation
            candidate = candidate.rstrip(".?!;")
            # Strip wrapping quotes
            if (candidate.startswith('"') and candidate.endswith('"')) or (candidate.startswith("'") and candidate.endswith("'")):
                candidate = candidate[1:-1].strip()
            # Strip redundant words like "website", "site", "url"
            candidate = re.sub(r"^(?:website|site|url|webpage|page)\s+", "", candidate, flags=re.IGNORECASE).strip()
            # Strip trailing natural language modifiers (e.g. 'in browser', 'in a new tab', 'please')
            candidate = re.sub(
                r"\s+(?:in\s+(?:the\s+|my\s+|a\s+)?(?:web\s+)?browser|in\s+(?:a\s+)?new\s+tab|on\s+the\s+web|online|please|for\s+me)\b.*$",
                "",
                candidate,
                flags=re.IGNORECASE,
            ).strip()
            if candidate:
                extracted_target = candidate
                break

    if not extracted_target:
        # Check if an explicit domain appears anywhere in the query with navigation intent
        dom_match = DOMAIN_PATTERN.search(cleaned)
        if dom_match and any(v in q_lower for v in ("open", "visit", "go", "navigate", "browse", "launch")):
            extracted_target = dom_match.group(0).strip().rstrip(".?!;")

    if not extracted_target:
        return None

    target_lower = extracted_target.lower()

    # 4. Filter out approved applications
    if target_lower in apps:
        return None
    # Filter common app phrase variations
    for app in apps:
        if target_lower == f"the {app}" or target_lower == f"{app} app" or target_lower == f"{app} application":
            return None

    # 5. Filter out approved folders
    if target_lower in folders:
        return None
    for fld in folders:
        if (
            target_lower == f"my {fld}"
            or target_lower == f"{fld} folder"
            or target_lower == f"my {fld} folder"
            or target_lower == f"the {fld} folder"
        ):
            return None

    # 6. Filter out other assistant domain actions using word boundaries
    excluded_keywords = (
        "smart device", "smart devices", "light", "lights", "plug", "speaker",
        "channel", "discord", "slack", "telegram", "memory", "memories",
        "time", "clock", "date", "system info", "specs", "ram"
    )
    if not ("." in target_lower or target_lower.startswith("http")):
        for kw in excluded_keywords:
            if re.search(rf"\b{re.escape(kw)}\b", target_lower):
                return None

    # 7. Check if target starts with a prohibited scheme (e.g. javascript:, file:)
    for p in PROHIBITED_SCHEMES:
        if target_lower.startswith(f"{p}:"):
            return extracted_target

    # 8. Check if target has a domain pattern
    if "." in extracted_target and not any(c in extracted_target for c in (" ", "\t", ";", "&", "|", "$")):
        try:
            return normalize_and_validate_url(extracted_target)
        except ValueError:
            return extracted_target

    # 9. Handle bare single-word website names (e.g. 'Instagram', 'YouTube', 'Reddit', 'GitHub')
    # If it is a clean alphanumeric identifier without spaces, resolve dynamically
    if re.match(r"^[a-zA-Z0-9_-]+$", extracted_target):
        # Resolve to standard canonical domain
        resolved_url = f"https://www.{target_lower}.com"
        try:
            return normalize_and_validate_url(resolved_url)
        except ValueError:
            return f"https://{target_lower}.com"

    return None


def is_website_navigation_query(
    query: str,
    app_allowlist: Optional[Set[str]] = None,
    approved_folders: Optional[Set[str]] = None,
) -> bool:
    """Return True if the query is a recognized website navigation directive."""
    target = extract_website_target_from_query(
        query,
        app_allowlist=app_allowlist,
        approved_folders=approved_folders,
    )
    return target is not None
