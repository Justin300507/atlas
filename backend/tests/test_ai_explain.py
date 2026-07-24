import sys
import types

from app.ai_explain import (
    AnthropicExplainer,
    DeterministicExplainer,
    architecture_summary_evidence,
    critical_module_explanation_evidence,
    finding_evidence,
    hotspot_explanation_evidence,
)
from app.models import (
    ArchitectureHealth,
    CouplingIssue,
    CriticalModule,
    EngineeringHotspot,
    QualityIssue,
    SemanticReport,
    SubsystemOverview,
)


def _semantic(**overrides) -> SemanticReport:
    defaults = dict(
        architecture_health=ArchitectureHealth(
            module_count=5, import_edge_count=8, circular_cluster_count=1,
            articulation_point_count=2, bridge_count=1, betweenness_computed=True,
            dependency_concentration_top5_ratio=0.42,
        ),
        critical_modules=[CriticalModule(file="hub.py", fan_in=4, fan_out=1, betweenness=0.5, criticality_score=9.1)],
        subsystem_overview=SubsystemOverview(confident=True, coverage_ratio=0.8, layer_counts={"service": 3}, layer_edges=[]),
        hotspots=[EngineeringHotspot(file="hub.py", churn=5, centrality=0.5, complexity_issues=2, hotspot_score=7.2)],
        coupling_issues=[],
        architectural_smells=[],
    )
    defaults.update(overrides)
    return SemanticReport(**defaults)


# --- DeterministicExplainer -------------------------------------------------


def test_deterministic_explainer_renders_grounded_template():
    evidence = architecture_summary_evidence(_semantic())
    result = DeterministicExplainer().explain("architecture_summary", evidence)

    assert result.source == "deterministic"
    assert "5 modules" in result.text
    assert result.grounded_in == evidence["_grounded_in"]


def test_deterministic_explainer_unknown_prompt_kind():
    result = DeterministicExplainer().explain("not_a_real_kind", {"_grounded_in": []})

    assert "No deterministic explanation template" in result.text
    assert result.source == "deterministic"


def test_deterministic_explainer_missing_evidence_is_honest_not_silent():
    result = DeterministicExplainer().explain("architecture_summary", {"_grounded_in": []})

    assert "Insufficient evidence" in result.text


def test_critical_module_evidence_returns_none_when_not_flagged():
    assert critical_module_explanation_evidence(_semantic(), "not_flagged.py") is None


def test_hotspot_evidence_returns_none_when_not_flagged():
    assert hotspot_explanation_evidence(_semantic(), "not_flagged.py") is None


def test_finding_evidence_handles_findings_with_and_without_line():
    with_line = finding_evidence(QualityIssue(file="a.py", line=12, kind="high_complexity", message="m", severity="important"))
    assert "line 12" in with_line["_grounded_in"][0]
    assert with_line["location"] == " at line 12"

    without_line = finding_evidence(CouplingIssue(file="b.py", kind="god_module", message="m", severity="critical"))
    assert "line" not in without_line["_grounded_in"][0]
    assert without_line["location"] == ""

    result = DeterministicExplainer().explain("finding_explanation", without_line)
    assert result.text == "Atlas flagged 'god_module' (critical severity) in b.py: m"


# --- AnthropicExplainer ------------------------------------------------------


def test_anthropic_explainer_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv("ATLAS_ANTHROPIC_API_KEY", raising=False)
    evidence = architecture_summary_evidence(_semantic())

    result = AnthropicExplainer().explain("architecture_summary", evidence)

    assert result.source == "deterministic"


def test_anthropic_explainer_falls_back_when_sdk_not_installed(monkeypatch):
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setitem(sys.modules, "anthropic", None)  # simulates ImportError
    evidence = architecture_summary_evidence(_semantic())

    result = AnthropicExplainer().explain("architecture_summary", evidence)

    assert result.source == "deterministic"


def _install_fake_anthropic_module(monkeypatch, *, response=None, raises=None):
    fake_module = types.ModuleType("anthropic")

    class _FakeClient:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            if raises is not None:
                raise raises
            return response

    fake_module.Anthropic = _FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    monkeypatch.setenv("ATLAS_ANTHROPIC_API_KEY", "sk-fake")


def test_anthropic_explainer_uses_mocked_client_success_path(monkeypatch):
    text_block = types.SimpleNamespace(type="text", text="Mocked grounded explanation.")
    fake_response = types.SimpleNamespace(stop_reason="end_turn", content=[text_block])
    _install_fake_anthropic_module(monkeypatch, response=fake_response)

    evidence = architecture_summary_evidence(_semantic())
    result = AnthropicExplainer().explain("architecture_summary", evidence)

    assert result.source == "anthropic"
    assert result.text == "Mocked grounded explanation."
    assert result.grounded_in == evidence["_grounded_in"]


def test_anthropic_explainer_falls_back_on_refusal(monkeypatch):
    fake_response = types.SimpleNamespace(stop_reason="refusal", content=[])
    _install_fake_anthropic_module(monkeypatch, response=fake_response)

    evidence = architecture_summary_evidence(_semantic())
    result = AnthropicExplainer().explain("architecture_summary", evidence)

    assert result.source == "deterministic"


def test_anthropic_explainer_falls_back_on_any_request_exception(monkeypatch):
    _install_fake_anthropic_module(monkeypatch, raises=RuntimeError("network down"))

    evidence = architecture_summary_evidence(_semantic())
    result = AnthropicExplainer().explain("architecture_summary", evidence)

    assert result.source == "deterministic"


def test_anthropic_explainer_falls_back_on_empty_text(monkeypatch):
    fake_response = types.SimpleNamespace(stop_reason="end_turn", content=[])
    _install_fake_anthropic_module(monkeypatch, response=fake_response)

    evidence = architecture_summary_evidence(_semantic())
    result = AnthropicExplainer().explain("architecture_summary", evidence)

    assert result.source == "deterministic"
