from providers.microsoft_common import normalize_azure_token


def test_normalize_azure_token_strips_bearer_prefix():
    assert normalize_azure_token("Bearer abc.def.ghi") == "abc.def.ghi"


def test_normalize_azure_token_extracts_json_access_token():
    assert (
        normalize_azure_token('{"accessToken":"abc.def.ghi","expiresOn":"2026-01-01"}')
        == "abc.def.ghi"
    )


def test_normalize_azure_token_uses_first_line_only():
    assert normalize_azure_token("abc.def.ghi\nsecond-line") == "abc.def.ghi"
