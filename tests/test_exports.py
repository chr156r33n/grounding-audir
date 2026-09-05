import csv
import io
import json

from core.enums import MatchMode, ObservationState
from core.export import CSV_COLUMNS, export_csv, export_json
from core.models import GroundingRequest, Target
from providers.openai_web import OpenAIWebProvider


def _request():
    return GroundingRequest(
        "run-1",
        "best hotel",
        [Target("example.com", MatchMode.ROOT_DOMAIN)],
        market="en-GB",
        language="en",
    )


def test_json_excludes_raw_by_default_and_redacts_when_included():
    request = _request()
    run = OpenAIWebProvider().new_run(request)
    run.raw_response = {
        "api_key": "must-not-leak",
        "nested": {"authorization": "Bearer secret-token"},
        "usage": {"input_tokens": 42},
    }
    without_raw = json.loads(export_json(request, [run]))
    assert "raw_response" not in without_raw["provider_runs"][0]
    with_raw_text = export_json(request, [run], include_raw=True)
    assert "must-not-leak" not in with_raw_text
    assert "secret-token" not in with_raw_text
    assert "[REDACTED]" in with_raw_text
    assert json.loads(with_raw_text)["provider_runs"][0]["raw_response"]["usage"]["input_tokens"] == 42


def test_csv_has_stable_columns_and_provider_level_failure_row():
    request = _request()
    run = OpenAIWebProvider().new_run(request)
    run.target_retrieved = ObservationState.UNKNOWN
    run.target_cited = ObservationState.NO
    rows = list(csv.DictReader(io.StringIO(export_csv(request, [run]))))
    assert list(rows[0]) == CSV_COLUMNS
    assert rows[0]["provider_id"] == "openai_web"
    assert rows[0]["retrieved"] == "unknown"
    assert rows[0]["cited"] == "no"
