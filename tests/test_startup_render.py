from lib.schema import SourceOutcome
from lib.startup_facts import extract_profile
from lib.startup_identity import build_identity
from lib.startup_public_base import item
from lib.startup_render import render_group, render_profile
from lib.startup_schema import GroupProfile


def profile(name, source="screener"):
    identity = build_identity(name, state="resolved", confidence="high")
    source_item = item(source, identity.entity_id, url=f"https://{source}.example/{name.lower()}", title=name, body="Revenue: INR 10 crore <script>alert(1)</script>", published_at="2025-01-02", metadata={"structured_facts": {"revenue": "INR 10 crore", "product": f"{name} product"}})
    return extract_profile(identity, [source_item])


def test_single_report_contains_required_sections_and_safe_source_link():
    value = profile("Alpha")
    rendered = render_profile(value, source_outcomes={"screener": SourceOutcome("screener", "ok", 1)})
    for heading in ("Coverage and source status", "Executive snapshot", "Identity and facts", "Product, market, and traction", "Team", "Funding and financial timeline", "Community and media", "Qualitative GOAT rubric", "Risks and unknowns", "Source matrix", "Evidence ledger and citations"):
        assert f"## {heading}" in rendered
    assert "<script>" not in rendered
    assert "INR 10 crore" in rendered
    assert value.identity.entity_id in rendered
    assert "screener.example" in rendered


def test_group_report_isolated_and_has_no_composite_score():
    alpha, beta = profile("Alpha"), profile("Beta")
    rendered = render_group(GroupProfile([alpha, beta]), dimensions=["product", "traction"])
    assert "Comparison matrix" in rendered
    assert "Alpha product" in rendered and "Beta product" in rendered
    assert "score:" not in rendered.lower()
    assert alpha.identity.entity_id in rendered and beta.identity.entity_id in rendered
    # Requested dimensions only in matrix, while profiles can retain full sections.
    matrix = rendered.split("## Comparison matrix", 1)[1].split("*Comparison", 1)[0]
    assert "Product" in matrix and "Traction" in matrix
    assert "Funding" not in matrix


def test_missing_facts_are_explicit_unknowns():
    value = profile("Sparse")
    rendered = render_profile(value)
    assert "Unknown" in rendered
    assert "what would change the assessment" in rendered.lower()
