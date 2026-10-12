"""Analysis pipeline: per-artifact facts + cross-artifact dependency graph."""
from __future__ import annotations

from typing import Callable, Dict

from ..model import Analysis, Artifact, Dependency, DocumentationSet
from . import rules, servicenow_js
from .common import code_metrics, strip_comments

# (platform, language) -> analyzer. "*" matches any platform.
ANALYZERS: Dict[tuple, Callable[[Artifact], Analysis]] = {
    ("servicenow", "javascript"): servicenow_js.analyze,
    ("*", "rule"): rules.analyze,
}


def _basic(artifact: Artifact) -> Analysis:
    a = Analysis()
    a.lines_of_code, a.complexity = code_metrics(strip_comments(artifact.all_code))
    return a


def analyze_artifact(artifact: Artifact) -> Analysis:
    fn = ANALYZERS.get((artifact.platform, artifact.language)) or ANALYZERS.get(("*", artifact.language)) or _basic
    return fn(artifact)


def analyze(docset: DocumentationSet) -> DocumentationSet:
    for artifact in docset.artifacts:
        artifact.analysis = analyze_artifact(artifact)
    docset.dependencies = resolve_dependencies(docset)
    return docset


def resolve_dependencies(docset: DocumentationSet) -> list:
    """Link artifacts that call, trigger or configure each other within the delivery."""
    by_name: Dict[str, Artifact] = {}
    for a in docset.artifacts:
        by_name.setdefault(a.name.lower(), a)
        by_name.setdefault(a.id.lower(), a)  # e.g. SuccessFactors rule ids
        if "." in a.name:  # scoped api names: x_acme.MyUtil
            by_name.setdefault(a.name.split(".")[-1].lower(), a)
    events: Dict[str, list] = {}
    for a in docset.artifacts:
        event = a.trigger.get("event")
        if event:
            events.setdefault(str(event).lower(), []).append(a)

    tables: Dict[str, Artifact] = {}
    for a in docset.artifacts:
        if a.type in ("table", "mdf_object"):
            tables[str(a.properties.get("Table name") or a.id).lower()] = a

    deps, seen = [], set()

    def add(src: Artifact, dst: Artifact, reason: str) -> None:
        if src.key != dst.key and (src.key, dst.key) not in seen:
            seen.add((src.key, dst.key))
            deps.append(Dependency(src.key, dst.key, reason))

    for a in docset.artifacts:
        for ref in a.analysis.references:
            target = by_name.get(ref.lower())
            if target:
                add(a, target, "calls")
        for ev in a.analysis.events_fired:
            for handler in events.get(ev.lower(), []):
                add(a, handler, f"fires event '{ev}'")
        for prop in a.analysis.properties_used:
            target = by_name.get(prop.lower())
            if target and target.type == "system_property":
                add(a, target, "reads property")
        for table in a.analysis.tables_written:
            if table.lower() in tables:
                add(a, tables[table.lower()], "writes table")
        for table in [a.target, *a.analysis.tables_read]:
            if table and table.lower() in tables:
                add(a, tables[table.lower()], "field of" if a.type == "dictionary" else "reads table")
        for step in a.steps:
            target = by_name.get(step.label.lower())
            if target and step.kind in ("action", "subflow"):
                add(a, target, f"uses {step.kind}")
    return deps
