import inspect
from unittest.mock import patch

import pytest

from core.query_discovery_compat import (
    QueryDiscoveryCompatibilityError,
    call_discover_queries,
    installed_query_discovery_version,
)


def test_installed_query_discovery_version_is_current():
    assert installed_query_discovery_version() >= 2


def test_call_discover_queries_filters_unsupported_kwargs():
    def fake_discover_queries(source_url, *, count=6, debug=False):
        return {"source_url": source_url, "count": count, "debug": debug}

    with patch(
        "core.query_discovery_compat._discover_queries_fn",
        return_value=fake_discover_queries,
    ):
        result = call_discover_queries(
            "https://example.com",
            count=4,
            debug=True,
            page_content="ignored by old runtime",
        )
    assert result["count"] == 4
    assert result["debug"] is True


def test_call_discover_queries_errors_when_paste_unsupported_after_reload():
    def fake_discover_queries(source_url, *, count=6):
        return source_url

    with patch(
        "core.query_discovery_compat._discover_queries_fn",
        return_value=fake_discover_queries,
    ), patch("core.query_discovery_compat._reload_query_discovery_modules"):
        with pytest.raises(QueryDiscoveryCompatibilityError, match="Reboot app"):
            call_discover_queries(
                "https://example.com",
                page_content="<html><body><p>Example copy long enough for tests.</p></body></html>",
            )


def test_real_discover_queries_accepts_page_content():
    from core.query_discovery import discover_queries

    assert "page_content" in inspect.signature(discover_queries).parameters
