"""Lightweight query-discovery constants for UI and fetch logic."""

QUERY_DISCOVERY_API_VERSION = 2

FETCH_PROFILES = {
    "browser": "Browser-like request (recommended for WAF-protected sites)",
    "transparent": "Transparent observatory bot User-Agent",
}
DEFAULT_FETCH_PROFILE = "browser"
TRANSPARENT_USER_AGENT = "GroundingSourceObservatory/1.0 (+research query discovery)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
