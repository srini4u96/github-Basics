"""Deterministic, offline explainer.

Builds the walkthrough from metadata + static analysis only, so it works with
no network access and never sends code anywhere. The Claude explainer builds
on the same facts and adds a narrative, line-by-line walkthrough.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List

from ..model import SEVERITY_ORDER, Artifact, DocumentationSet
from .base import Explainer

CLIENT_TYPES = {"onLoad": "when the form loads", "onSubmit": "when the form is submitted",
                "onCellEdit": "when a cell is edited in a list"}
SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡", "info": "ℹ️"}


def _code(value: str) -> str:
    return f"`{value}`" if value else ""


def _join(items: List[str], code: bool = True) -> str:
    items = [_code(i) if code else i for i in items]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def summary_sentence(a: Artifact) -> str:
    t, target = a.trigger, _code(a.target)
    if a.platform == "successfactors" and a.type == "business_rule":
        return (f"Business rule on {target or 'its base object'}"
                + (f" for the **{t['scenario']}** scenario" if t.get("scenario") else "")
                + (f", fired **{t['event']}**" if t.get("event") else "") + f", with {len(a.steps)} condition block(s).")
    if a.type == "business_rule":
        past = {"insert": "inserted", "update": "updated", "delete": "deleted", "query": "queried"}
        ops = _join([past.get(o, o) for o in t.get("operations", [])], code=False) or "saved"
        cond = f", only when `{t['condition']}`" if t.get("condition") else ""
        if t.get("filter_condition"):
            cond += f" (filter: `{t['filter_condition']}`)"
        return f"Server-side rule that runs **{t.get('when', '')}** a record is **{ops}** on {target}{cond}."
    if a.type in ("client_script", "catalog_client_script"):
        kind = t.get("type", "")
        moment = (f"when the `{t.get('field') or t.get('variable')}` field changes" if kind == "onChange"
                  else CLIENT_TYPES.get(kind, kind))
        return f"Browser-side script that runs {moment} on {target or 'the form'}."
    if a.type == "script_include":
        fns = [f for f in a.analysis.functions][:8]
        return (f"Reusable server-side library, {t.get('invoked', 'called on demand')},"
                + (f" exposing {_join(fns)}." if fns else "."))
    if a.type == "ui_action":
        where = _join(t.get("shown_as", []), code=False) or "button/link"
        return f"{where} on {target} that runs a script when clicked" + (
            f" (visible when `{t['condition']}`)." if t.get("condition") else ".")
    if a.type == "ui_policy":
        return f"Form behaviour on {target} applied when `{t.get('conditions', 'always')}`."
    if a.type == "scheduled_job":
        when = " ".join(str(v).replace("1970-01-01 ", "at ") for v in (t.get("run"), t.get("day"), t.get("time"), t.get("period")) if v)
        return f"Background job that runs on a schedule ({when or 'see schedule'})."
    if a.type in ("script_action", "notification") and t.get("event"):
        what = "Sends an email notification" if a.type == "notification" else "Runs a script"
        return f"{what} when the `{t['event']}` event is fired" + (f" for {target} records." if a.target else ".")
    if a.type == "notification":
        ops = [op for op, key in (("inserted", "on_insert"), ("updated", "on_update")) if str(t.get(key)).lower() == "true"]
        return f"Sends an email notification when a {target} record is {_join(ops, code=False) or 'changed'}."
    if a.type == "scripted_rest":
        return f"REST endpoint `{t.get('method', '')} {t.get('path', '')}` exposed by API {_code(t.get('api', ''))}."
    if a.type == "flow":
        trig = t.get("type", "")
        on = f" on {_code(t['table'])}" if t.get("table") else ""
        cond = f" when `{t['condition']}`" if t.get("condition") else ""
        return (f"Flow Designer {a.properties.get('Flow type', 'flow')} triggered by **{trig or 'its trigger'}**{on}{cond}, "
                f"with {len(a.steps)} step(s).")
    if a.type == "dictionary":
        return (f"Field `{a.target}.{a.name}` ({a.properties.get('Type', 'field')}"
                + (f" referencing `{a.properties['Reference']}`" if a.properties.get("Reference") else "") + ").")
    if a.type == "system_property":
        return f"Configuration value `{a.name}` = `{a.properties.get('Value', '')}`."
    if a.type == "integration":
        return (f"Integration from {target or 'SuccessFactors'} to {_code(str(a.properties.get('Destination', '')))}"
                f" mapping {len(a.steps)} field(s)" + (f", scheduled {t['schedule']}" if t.get("schedule") else "") + ".")
    if a.type == "mdf_object":
        return f"Custom MDF object with {len(a.steps)} field(s)."
    if a.type == "workflow":
        return f"Approval workflow with {len(a.steps)} step(s)."
    trigger = ", ".join(f"{k}: {v}" for k, v in t.items())
    return f"{a.type_label}{' on ' + target if a.target else ''}{' (' + trigger + ')' if trigger else ''}."


def _developer_notes(code: str) -> List[str]:
    """Comments the developer left in the code are often the best explanation available."""
    notes = []
    for m in re.finditer(r"//[ \t]*([^\n]+)|/\*+\s*(.*?)\*/", code or "", re.S):
        text = re.sub(r"\s*\n\s*\*?\s*", " ", (m.group(1) or m.group(2) or "")).strip(" *")
        if len(text) > 12 and not re.match(r"^[-=*_#]+$", text):
            notes.append(text)
    return notes[:10]


class TemplateExplainer(Explainer):
    def explain_artifact(self, a: Artifact, docset: DocumentationSet) -> str:
        an = a.analysis
        out: List[str] = [f"**In short:** {summary_sentence(a)}", ""]
        if a.description:
            out += [f"**Purpose (from the record):** {a.description}", ""]
        if a.deleted:
            out += ["> ⚠️ This record is **deleted** by this delivery.", ""]

        does: List[str] = []
        if an.tables_read:
            does.append(f"Reads {_join(an.tables_read)}")
        if an.tables_written:
            does.append(f"Writes to (create/update/delete) {_join(an.tables_written)}")
        if an.fields_set:
            does.append(f"Sets field(s) {_join(an.fields_set)}")
        calls = [r for r in an.references if not any(f"`{r}`" in b for b in an.behaviours)]
        if calls:
            does.append(f"Calls {_join(calls)}")
        if an.events_fired:
            does.append(f"Fires event(s) {_join(an.events_fired)}")
        if an.properties_used:
            does.append(f"Reads configuration {_join(an.properties_used)}")
        if an.integrations:
            does.append(f"Calls external system(s): {_join(an.integrations)}")
        does += an.behaviours
        if does:
            out += ["### What it does", *[f"- {d}" for d in does], ""]

        if a.steps:
            out.append("### Step by step")
            for i, step in enumerate(a.steps, start=1):
                detail = f" — {step.detail}" if step.detail else ""
                out.append(f"{i}. **{step.label}**{detail} _({step.kind})_")
            out.append("")
        elif an.functions:
            out += ["### Functions", *[f"- `{fn}()`" for fn in an.functions], ""]

        notes = _developer_notes(a.all_code)
        if notes:
            out += ["### Developer notes (from code comments)", *[f"- {n}" for n in notes], ""]

        keys = docset.by_key()
        uses = [f"{keys[d.target].type_label} **{keys[d.target].name}** ({d.reason})"
                for d in docset.dependencies if d.source == a.key and d.target in keys]
        used_by = [f"{keys[d.source].type_label} **{keys[d.source].name}** ({d.reason})"
                   for d in docset.dependencies if d.target == a.key and d.source in keys]
        if uses or used_by:
            out.append("### Connections in this delivery")
            out += [f"- Uses → {u}" for u in uses] + [f"- Used by ← {u}" for u in used_by]
            out.append("")

        if an.findings:
            out.append("### Review notes")
            for f in sorted(an.findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9)):
                out.append(f"- {SEVERITY_ICON.get(f.severity, '')} **{f.severity}** — {f.message}")
            out.append("")
        return "\n".join(out).strip()

    def overview(self, docset: DocumentationSet) -> str:
        counts = Counter(a.type_label for a in docset.artifacts)
        meta = docset.metadata
        out: List[str] = []
        if meta.get("update_set"):
            out.append(f"This delivery is update set **{meta['update_set']}**"
                       + (f" ({meta['application']})" if meta.get("application") else "") + ".")
        if meta.get("update_set_description"):
            out.append(f"\n> {meta['update_set_description']}\n")
        out.append(f"It contains **{len(docset.artifacts)}** component(s): "
                   + _join([f"{n} × {label}" for label, n in counts.most_common()], code=False) + ".")
        authors = Counter(a.updated_by or a.author for a in docset.artifacts if a.updated_by or a.author)
        if authors:
            out.append("Built by " + _join([f"{who} ({n})" for who, n in authors.most_common()], code=False) + ".")

        tables: Dict[str, int] = Counter()
        for a in docset.artifacts:
            for t in {a.target, *a.analysis.tables_read, *a.analysis.tables_written} - {""}:
                tables[t] += 1
        if tables:
            out += ["", "**Data touched:** " + _join([t for t, _ in tables.most_common()]) + "."]

        keys = docset.by_key()
        if docset.dependencies:
            out += ["", "### How the pieces fit together"]
            for d in docset.dependencies:
                s, t = keys.get(d.source), keys.get(d.target)
                if s and t:
                    out.append(f"- {s.type_label} **{s.name}** {d.reason} → {t.type_label} **{t.name}**")
        entry_points = [a for a in docset.artifacts
                        if not any(d.target == a.key for d in docset.dependencies)
                        and a.type in ("business_rule", "client_script", "catalog_client_script", "ui_action",
                                       "flow", "scheduled_job", "scripted_rest", "ui_policy", "integration")]
        if entry_points:
            out += ["", "### Where to start reading",
                    "These components are triggered by users, data changes or schedules (entry points):"]
            out += [f"- {a.type_label} **{a.name}** — {summary_sentence(a)}" for a in entry_points]
        findings = [(a, f) for a in docset.artifacts for f in a.analysis.findings if f.severity in ("high", "medium")]
        if findings:
            out += ["", "### Review hot spots"]
            for a, f in sorted(findings, key=lambda x: SEVERITY_ORDER[x[1].severity]):
                out.append(f"- {SEVERITY_ICON[f.severity]} **{a.name}** — {f.message}")
        return "\n".join(out).strip()
