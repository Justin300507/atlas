from __future__ import annotations

import os
import string
from typing import Protocol

from .models import ExplanationResponse, SemanticReport

# See docs/superpowers/specs/2026-07-24-engineering-advisor-suite-design.md.
#
# Product rule: AI explains deterministic findings, it never invents them.
# Every explainer takes a pre-built `evidence` dict whose "_grounded_in" key
# is the exact list of deterministic facts the explanation is allowed to
# discuss. DeterministicExplainer is template-only and always succeeds --
# it is both the default explainer and AnthropicExplainer's fallback, so
# "no API key configured" or "network/SDK unavailable" degrade to the same
# grounded output a user would get with AI off entirely.

_DEFAULT_MODEL = "claude-opus-4-8"


class Explainer(Protocol):
    def explain(self, prompt_kind: str, evidence: dict[str, object]) -> ExplanationResponse: ...


_TEMPLATES: dict[str, string.Template] = {
    "architecture_summary": string.Template(
        "This repository has $module_count modules connected by $import_edge_count "
        "import edge(s). $circular_cluster_count circular-dependency cluster(s), "
        "$articulation_point_count articulation point(s) (modules whose removal "
        "would disconnect part of the import graph), and $bridge_count bridge "
        "edge(s) were found. The top 5 modules by import concentration account "
        "for $dependency_concentration_top5_ratio_pct% of all import edges."
    ),
    "subsystem_summary": string.Template(
        "Layer detection is $confidence_word for this repository "
        "(coverage: $coverage_ratio_pct% of modules assigned to a layer). "
        "Layer distribution: $layer_counts_text."
    ),
    "dependency_explanation": string.Template(
        "The top 5 modules by import concentration account for "
        "$dependency_concentration_top5_ratio_pct% of all import edges. "
        "$articulation_point_count module(s) are articulation points -- "
        "removing any one of them would disconnect part of the import graph."
    ),
    "critical_module_explanation": string.Template(
        "$file has a dependency-criticality score of $criticality_score "
        "(fan-in $fan_in, fan-out $fan_out, betweenness centrality $betweenness). "
        "High fan-in means many modules import it directly; high betweenness "
        "means it sits on many shortest import paths between other module pairs."
    ),
    "layer_explanation": string.Template(
        "Detected layers: $layer_counts_text. $layer_edge_count distinct "
        "cross-layer import edge type(s) were observed."
    ),
    "hotspot_explanation": string.Template(
        "$file has hotspot score $hotspot_score, combining $churn recent "
        "commit(s) touching the file with its dependency-criticality "
        "contribution and $complexity_issues complexity issue(s) "
        "(long/high-complexity functions)."
    ),
    "repository_overview": string.Template(
        "Overall score $overall_score/100 (maintainability $maintainability_score, "
        "architecture $architecture_score). $module_count module(s), "
        "$critical_module_count in the dependency-criticality top 15, "
        "$hotspot_count engineering hotspot(s), $smell_count architectural "
        "smell(s), $coupling_issue_count coupling issue(s)."
    ),
    "finding_explanation": string.Template(
        "Atlas flagged '$kind' ($severity severity) in $file$location: $message"
    ),
}


class DeterministicExplainer:
    """Template-based explainer. Always succeeds; never calls out to a network.

    Uses strict `Template.substitute` rather than `safe_substitute` -- if the
    evidence dict is missing a variable the template needs, that's a bug in
    the caller, and silently leaving a literal "$foo" in user-facing text is
    worse than saying plainly that the explanation could not be built.
    """

    def explain(self, prompt_kind: str, evidence: dict[str, object]) -> ExplanationResponse:
        grounded_in = [str(fact) for fact in evidence.get("_grounded_in", [])]
        template = _TEMPLATES.get(prompt_kind)
        if template is None:
            return ExplanationResponse(
                text=f"No deterministic explanation template exists for '{prompt_kind}'.",
                source="deterministic",
                grounded_in=grounded_in,
            )
        template_vars = {k: v for k, v in evidence.items() if not k.startswith("_")}
        try:
            text = template.substitute(**template_vars)
        except KeyError as exc:
            return ExplanationResponse(
                text=f"Insufficient evidence to explain '{prompt_kind}': missing {exc}.",
                source="deterministic",
                grounded_in=grounded_in,
            )
        return ExplanationResponse(text=text, source="deterministic", grounded_in=grounded_in)


class AnthropicExplainer:
    """Explains deterministic evidence via a real Claude API call.

    Falls back to `self._fallback` (a DeterministicExplainer by default) on
    ANY failure -- no ATLAS_ANTHROPIC_API_KEY set, the `anthropic` SDK not
    installed, a network/API error, or a safety refusal. This is
    deliberate: "AI unavailable" must never make Atlas's own output less
    reliable than running with AI off.
    """

    def __init__(self, model: str | None = None, fallback: Explainer | None = None) -> None:
        self._model = model or os.environ.get("ATLAS_ANTHROPIC_MODEL", _DEFAULT_MODEL)
        self._fallback = fallback or DeterministicExplainer()

    def explain(self, prompt_kind: str, evidence: dict[str, object]) -> ExplanationResponse:
        deterministic = self._fallback.explain(prompt_kind, evidence)

        api_key = os.environ.get("ATLAS_ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            return deterministic

        try:
            import anthropic
        except ImportError:
            return deterministic

        grounded_facts = [str(fact) for fact in evidence.get("_grounded_in", [])]
        prompt = (
            "You are explaining a deterministic static-analysis finding from "
            "Atlas, a code-analysis tool. Explain ONLY the facts listed below, "
            "in plain engineering language. Do not invent, estimate, or add any "
            "fact not listed here. If the facts are insufficient to say "
            "anything useful, say so explicitly instead of guessing.\n\n"
            "Facts:\n" + "\n".join(f"- {fact}" for fact in grounded_facts) + "\n\n"
            "Deterministic baseline explanation (for reference; reuse it "
            f"verbatim if it is already clear): {deterministic.text}"
        )

        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=self._model,
                max_tokens=512,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception:
            # Any SDK/network/API failure degrades to the deterministic
            # explanation -- see class docstring.
            return deterministic

        if response.stop_reason == "refusal":
            return deterministic

        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text:
            return deterministic

        return ExplanationResponse(text=text, source="anthropic", grounded_in=grounded_facts)


def insufficient_evidence(reason: str) -> ExplanationResponse:
    return ExplanationResponse(text=f"Insufficient evidence: {reason}", source="deterministic", grounded_in=[])


# ---------------------------------------------------------------------------
# Evidence builders -- AI Architect. Each returns None (never a partial /
# guessed dict) when the requested subject isn't present in the semantic
# report, so callers can turn that into a clean "insufficient evidence"
# response rather than explaining something Atlas didn't actually find.
# ---------------------------------------------------------------------------


def architecture_summary_evidence(semantic: SemanticReport) -> dict[str, object]:
    h = semantic.architecture_health
    facts = [
        f"{h.module_count} modules",
        f"{h.import_edge_count} import edges",
        f"{h.circular_cluster_count} circular-dependency cluster(s)",
        f"{h.articulation_point_count} articulation point(s)",
        f"{h.bridge_count} bridge edge(s)",
    ]
    return {
        "module_count": h.module_count,
        "import_edge_count": h.import_edge_count,
        "circular_cluster_count": h.circular_cluster_count,
        "articulation_point_count": h.articulation_point_count,
        "bridge_count": h.bridge_count,
        "dependency_concentration_top5_ratio_pct": round(h.dependency_concentration_top5_ratio * 100, 1),
        "_grounded_in": facts,
    }


def _layer_counts_text(layer_counts: dict[str, int]) -> str:
    return ", ".join(f"{k}: {v}" for k, v in sorted(layer_counts.items())) or "none detected"


def subsystem_summary_evidence(semantic: SemanticReport) -> dict[str, object]:
    o = semantic.subsystem_overview
    confidence_word = (
        "confident"
        if o.confident
        else "low-confidence -- insufficient evidence for reliable layer assignment"
    )
    facts = [f"layer coverage {round(o.coverage_ratio * 100, 1)}%", f"confident={o.confident}"]
    return {
        "confidence_word": confidence_word,
        "coverage_ratio_pct": round(o.coverage_ratio * 100, 1),
        "layer_counts_text": _layer_counts_text(o.layer_counts),
        "_grounded_in": facts,
    }


def dependency_explanation_evidence(semantic: SemanticReport) -> dict[str, object]:
    h = semantic.architecture_health
    facts = [
        f"top-5 import concentration {round(h.dependency_concentration_top5_ratio * 100, 1)}%",
        f"{h.articulation_point_count} articulation point(s)",
    ]
    return {
        "dependency_concentration_top5_ratio_pct": round(h.dependency_concentration_top5_ratio * 100, 1),
        "articulation_point_count": h.articulation_point_count,
        "_grounded_in": facts,
    }


def critical_module_explanation_evidence(semantic: SemanticReport, file: str) -> dict[str, object] | None:
    match = next((m for m in semantic.critical_modules if m.file == file), None)
    if match is None:
        return None
    facts = [
        f"criticality score {match.criticality_score:.2f}",
        f"fan-in {match.fan_in}",
        f"fan-out {match.fan_out}",
        f"betweenness {match.betweenness:.4f}",
    ]
    return {
        "file": match.file,
        "criticality_score": round(match.criticality_score, 2),
        "fan_in": match.fan_in,
        "fan_out": match.fan_out,
        "betweenness": round(match.betweenness, 4),
        "_grounded_in": facts,
    }


def layer_explanation_evidence(semantic: SemanticReport) -> dict[str, object]:
    o = semantic.subsystem_overview
    facts = [f"{len(o.layer_edges)} cross-layer edge type(s)"]
    return {
        "layer_counts_text": _layer_counts_text(o.layer_counts),
        "layer_edge_count": len(o.layer_edges),
        "_grounded_in": facts,
    }


def hotspot_explanation_evidence(semantic: SemanticReport, file: str) -> dict[str, object] | None:
    match = next((h for h in semantic.hotspots if h.file == file), None)
    if match is None:
        return None
    facts = [
        f"hotspot score {match.hotspot_score:.2f}",
        f"{match.churn} commit(s) churn",
        f"{match.complexity_issues} complexity issue(s)",
    ]
    return {
        "file": match.file,
        "hotspot_score": round(match.hotspot_score, 2),
        "churn": match.churn,
        "complexity_issues": match.complexity_issues,
        "_grounded_in": facts,
    }


def repository_overview_evidence(
    overall_score: int,
    maintainability_score: int,
    architecture_score: int,
    semantic: SemanticReport,
) -> dict[str, object]:
    facts = [
        f"overall score {overall_score}/100",
        f"{len(semantic.critical_modules)} critical module(s)",
        f"{len(semantic.hotspots)} hotspot(s)",
    ]
    return {
        "overall_score": overall_score,
        "maintainability_score": maintainability_score,
        "architecture_score": architecture_score,
        "module_count": semantic.architecture_health.module_count,
        "critical_module_count": len(semantic.critical_modules),
        "hotspot_count": len(semantic.hotspots),
        "smell_count": len(semantic.architectural_smells),
        "coupling_issue_count": len(semantic.coupling_issues),
        "_grounded_in": facts,
    }


# ---------------------------------------------------------------------------
# Evidence builder -- AI Mentor. `finding` is one of QualityIssue /
# SecurityIssue / CouplingIssue / ArchitecturalSmell -- all four share
# file/kind/message/severity; only Quality/SecurityIssue also have `line`.
# ---------------------------------------------------------------------------


def finding_evidence(finding: object) -> dict[str, object]:
    kind = finding.kind
    file = finding.file
    message = finding.message
    severity = finding.severity
    line = getattr(finding, "line", None)
    location = f" at line {line}" if line else ""
    facts = [f"{kind} ({severity}) in {file}" + (f" line {line}" if line else "")]
    return {
        "kind": kind,
        "file": file,
        "message": message,
        "severity": severity,
        "location": location,
        "_grounded_in": facts,
    }
