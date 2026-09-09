from core.matching import (
    citation_target_hints,
    is_grounding_redirect_url,
    matching_targets_for_citation,
)
from core.models import Target
from core.enums import MatchMode


def test_is_grounding_redirect_url():
    assert is_grounding_redirect_url(
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQ"
    )


def test_matching_targets_for_citation_uses_anchor_text_on_redirect():
    targets = [Target("fourseasons.com", MatchMode.ROOT_DOMAIN)]
    redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example"
    matches = matching_targets_for_citation(
        targets,
        redirect,
        cited_text="fourseasons.com",
    )
    assert matches == ["fourseasons.com"]


def test_citation_target_hints_normalizes_domain():
    assert citation_target_hints("fourseasons.com/hotels") == [
        "https://fourseasons.com/hotels",
        "https://fourseasons.com",
    ]
