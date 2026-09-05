from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract

from .enums import MatchMode
from .models import Target

_extract = tldextract.TLDExtract(suffix_list_urls=())
_TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "msclkid",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _with_scheme(value: str) -> str:
    value = value.strip()
    return value if "://" in value else f"https://{value}"


def _hostname(value: str) -> str | None:
    try:
        host = urlsplit(_with_scheme(value)).hostname
    except ValueError:
        return None
    if not host:
        return None
    return _valid_hostname(host)


def _valid_hostname(host: str) -> str | None:
    host = host.rstrip(".").lower()
    try:
        return ipaddress.ip_address(host).compressed
    except ValueError:
        pass
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    labels = ascii_host.split(".")
    if (
        not labels
        or len(ascii_host) > 253
        or any(not _HOST_LABEL.fullmatch(label) for label in labels)
    ):
        return None
    return ascii_host


def registrable_domain(value: str) -> str | None:
    host = _hostname(value)
    if not host:
        return None
    extracted = _extract(host)
    if not extracted.suffix:
        return host
    return extracted.top_domain_under_public_suffix.lower()


def normalize_url(value: str) -> str | None:
    """Conservatively normalize a web URL while retaining meaningful queries."""
    try:
        parsed = urlsplit(_with_scheme(value))
        host = _valid_hostname(parsed.hostname or "")
        if not host or parsed.scheme.lower() not in {"http", "https"}:
            return None
        try:
            port = parsed.port
        except ValueError:
            return None
        default_port = (parsed.scheme.lower() == "http" and port == 80) or (
            parsed.scheme.lower() == "https" and port == 443
        )
        rendered_host = f"[{host}]" if ":" in host else host
        netloc = rendered_host if port is None or default_port else f"{rendered_host}:{port}"
        if parsed.username or parsed.password:
            return None
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/")
        query = urlencode(
            [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
             if key.lower() not in _TRACKING_PARAMETERS],
            doseq=True,
        )
        return urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))
    except (TypeError, ValueError):
        return None


def target_matches_url(target: Target, candidate_url: str) -> bool:
    candidate = normalize_url(candidate_url)
    if not candidate:
        return False

    if target.match_mode is MatchMode.URL_PREFIX:
        prefix = normalize_url(target.value)
        if not prefix:
            return False
        candidate_parts = urlsplit(candidate)
        prefix_parts = urlsplit(prefix)
        if (
            candidate_parts.scheme != prefix_parts.scheme
            or candidate_parts.netloc != prefix_parts.netloc
            or (prefix_parts.query and candidate_parts.query != prefix_parts.query)
        ):
            return False
        prefix_path = prefix_parts.path.rstrip("/") or "/"
        candidate_path = candidate_parts.path.rstrip("/") or "/"
        return candidate_path == prefix_path or (
            prefix_path != "/" and candidate_path.startswith(f"{prefix_path}/")
        )

    target_host = _hostname(target.value)
    candidate_host = _hostname(candidate)
    if not target_host or not candidate_host:
        return False
    if target.match_mode is MatchMode.EXACT_HOSTNAME:
        return candidate_host == target_host
    return registrable_domain(target_host) == registrable_domain(candidate_host)


def matching_targets(targets: list[Target], candidate_url: str) -> list[str]:
    return [target.value for target in targets if target_matches_url(target, candidate_url)]
