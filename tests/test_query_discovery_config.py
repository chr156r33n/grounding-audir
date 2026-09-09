from core.query_discovery_config import DEFAULT_FETCH_PROFILE, FETCH_PROFILES, QUERY_DISCOVERY_API_VERSION


def test_fetch_profiles_available_from_config_module():
    assert QUERY_DISCOVERY_API_VERSION >= 2
    assert DEFAULT_FETCH_PROFILE in FETCH_PROFILES
    assert "browser" in FETCH_PROFILES
    assert "transparent" in FETCH_PROFILES
