"""Analysis for declarative rules (SuccessFactors Business Rules and similar).

Rules are expressed as ``Object.Field`` paths inside IF/THEN statements, e.g.
``Set Job Information.Probation Period End Date to AddMonths(...)``.
"""
from __future__ import annotations

import re
from typing import List

from ..model import Analysis, Artifact, Finding
from .common import add_unique

KEYWORDS = {"if", "else", "then", "and", "or", "not", "set", "to", "raise", "message", "execute", "rule",
            "trigger", "workflow", "event", "is", "equal", "always", "create", "delete", "severity"}
PATH = re.compile(r"([A-Za-z][\w ]*?)\.([A-Za-z][\w ]*?)(?=\s*(?:=|!=|<|>|\bto\b|\bis\b|,|\)|$|\.|\bAND\b|\bOR\b))", re.M)
SET_STMT = re.compile(r"\bSet\s+([A-Za-z][\w ]*\.[\w ]+?)\s+(?:to|=)\s", re.I)
RULE_CALL = re.compile(r"\b(?:Execute|Call)\s+Rule\s+['\"]?([\w\-]+)", re.I)
WORKFLOW = re.compile(r"\bTrigger\s+Workflow\s+['\"]?([\w\-]+)", re.I)
EVENT = re.compile(r"\bRaise\s+Event\s+['\"]?([\w\-]+)", re.I)


def _object_name(phrase: str) -> str:
    """'ELSE IF Job Information' -> 'Job Information' (drop leading rule keywords)."""
    words = phrase.split()
    while words and words[0].lower() in KEYWORDS:
        words.pop(0)
    return " ".join(words)


def _text(artifact: Artifact) -> str:
    if artifact.all_code.strip():
        return artifact.all_code
    return "\n".join(f"{s.label}\n{s.detail}" for s in artifact.steps)


def analyze(artifact: Artifact) -> Analysis:
    a = Analysis()
    text = _text(artifact)
    if artifact.target:
        add_unique(a.tables_read, artifact.target)
    if not text.strip():
        _findings(artifact, a)
        return a
    a.lines_of_code = len([ln for ln in text.splitlines() if ln.strip()])
    a.complexity = 1 + len(re.findall(r"\b(?:IF|AND|OR)\b", text))

    written: List[str] = []
    for path in SET_STMT.findall(text):
        obj, field = path.split(".", 1)
        obj = _object_name(obj)
        add_unique(a.fields_set, f"{obj}.{field.strip()}")
        add_unique(written, obj)
    for obj, _field in PATH.findall(text):
        obj = _object_name(obj)
        if obj and obj not in written:
            add_unique(a.tables_read, obj)
    for obj in written:
        add_unique(a.tables_written, obj)

    for name in RULE_CALL.findall(text):
        add_unique(a.references, name)
        add_unique(a.behaviours, f"Executes rule `{name}`")
    for name in WORKFLOW.findall(text):
        add_unique(a.references, name)
        add_unique(a.behaviours, f"Starts workflow `{name}`")
    for name in EVENT.findall(text):
        add_unique(a.events_fired, name)
    if re.search(r"\bRaise\s+Message\b", text, re.I):
        add_unique(a.behaviours, "Shows a message to the user" +
                   (" (can block the save with an error)" if re.search(r"Severity:\s*Error", text, re.I) else ""))
    if re.search(r"\bDelete\b", text):
        add_unique(a.behaviours, "Deletes data")
    _findings(artifact, a)
    return a


def _findings(artifact: Artifact, a: Analysis) -> None:
    add = lambda sev, msg, rule: a.findings.append(Finding(sev, msg, rule))  # noqa: E731
    if artifact.type == "integration":
        dest = artifact.properties.get("Destination")
        if dest:
            add_unique(a.integrations, str(dest))
        if not artifact.steps:
            add("medium", "No field mappings found in the export.", "integration-no-mappings")
    if artifact.type == "business_rule":
        if not artifact.trigger.get("event") and not artifact.trigger.get("scenario"):
            add("medium", "Rule is not tied to an event or scenario - confirm where it is assigned "
                          "(object definition / rules trigger).", "rule-unassigned")
        if not artifact.steps:
            add("medium", "No rule definition was found in the export.", "rule-empty")
        if a.complexity > 12:
            add("medium", f"Complex rule (approx. {a.complexity} conditions) - consider splitting it.", "complexity")
    if artifact.active is False:
        add("info", "Artifact is inactive.", "inactive")
    if not artifact.description:
        add("low", "No description recorded.", "missing-description")
