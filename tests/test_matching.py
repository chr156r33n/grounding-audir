import pytest

from core.enums import MatchMode
from core.matching import normalize_url, registrable_domain, target_matches_url
from core.models import Target


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("https://www.fourseasons.com/", True),
        ("https://press.fourseasons.com/news", True),
        ("https://fourseasons.com/hongkong/", True),
        ("https://fourseasons.com.example.org/", False),
        ("https://notfourseasons.com/", False),
        ("not a URL", False),
    ],
)
def test_root_domain_matching(candidate, expected):
    target = Target("fourseasons.com", MatchMode.ROOT_DOMAIN)
    assert target_matches_url(target, candidate) is expected


def test_public_suffix_aware_matching():
    target = Target("example.co.uk", MatchMode.ROOT_DOMAIN)
    assert target_matches_url(target, "https://news.example.co.uk/story")
    assert registrable_domain("news.example.co.uk") == "example.co.uk"


def test_exact_hostname_is_case_and_trailing_dot_safe():
    target = Target("WWW.FourSeasons.com.", MatchMode.EXACT_HOSTNAME)
    assert target_matches_url(target, "https://www.fourseasons.com/path")
    assert not target_matches_url(target, "https://press.fourseasons.com/path")


def test_url_prefix_respects_path_boundaries():
    target = Target("https://www.fourseasons.com/hongkong/", MatchMode.URL_PREFIX)
    assert target_matches_url(target, "https://www.fourseasons.com/hongkong/rooms?view=all")
    assert not target_matches_url(target, "https://www.fourseasons.com/hongkong-offers")
    assert not target_matches_url(target, "http://www.fourseasons.com/hongkong/rooms")


def test_normalize_url_is_conservative():
    assert normalize_url("HTTPS://Example.COM:443/foo/#section") == "https://example.com/foo"
    assert (
        normalize_url("https://example.com/foo/?utm_source=test&id=42&fbclid=x")
        == "https://example.com/foo?id=42"
    )
    assert normalize_url("ftp://example.com/file") is None
    assert normalize_url("https://user:password@example.com/") is None
