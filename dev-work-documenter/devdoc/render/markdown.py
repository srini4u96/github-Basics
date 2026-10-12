"""Markdown output: an index page plus one page per artifact (ideal for Git wikis / Confluence import)."""
from __future__ import annotations

from pathlib import Path
from typing import List

from ..model import Artifact, DocumentationSet
from .common import artifact_slugs, mermaid_graph

FENCE_LANG = {"javascript": "javascript", "rule": "text", "flow": "text", "text": "text"}


def _status(a: Artifact) -> str:
    if a.deleted:
        return "deleted"
    return {True: "active", False: "inactive", None: "—"}[a.active]


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def artifact_page(a: Artifact, link_back: str = "") -> str:
    out: List[str] = [f"# {a.name}", ""]
    if link_back:
        out += [f"[← Back to overview]({link_back})", ""]
    rows = [("Type", a.type_label), ("Platform", a.platform), ("Applies to", f"`{a.target}`" if a.target else ""),
            ("Application", a.application), ("Status", _status(a)), ("Created by", a.author),
            ("Last updated", " by ".join(x for x in (a.updated_on, a.updated_by) if x)), ("Source", f"`{a.source}`")]
    rows += [(k, f"`{v}`" if k == "Record type" else str(v)) for k, v in a.properties.items()]
    rows += [(f"Trigger: {k}", ", ".join(map(str, v)) if isinstance(v, list) else f"`{v}`") for k, v in a.trigger.items()]
    out += ["| | |", "|---|---|"] + [f"| {k} | {_cell(v)} |" for k, v in rows if v]
    out += ["", "## Walkthrough", "", a.explanation or "_No explanation generated._", ""]
    m = a.analysis
    if m.lines_of_code:
        out += [f"_Size: {m.lines_of_code} lines, complexity ≈ {m.complexity}._", ""]
    for label, code in a.scripts.items():
        out += [f"## {label}", "", f"```{FENCE_LANG.get(a.language, a.language)}", code.rstrip(), "```", ""]
    return "\n".join(out)


def render(docset: DocumentationSet, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    pages = out_dir / "artifacts"
    pages.mkdir(parents=True, exist_ok=True)
    slugs = artifact_slugs(docset)
    for a in docset.artifacts:
        (pages / f"{slugs[a.key]}.md").write_text(artifact_page(a, "../README.md"), encoding="utf-8")

    out = [f"# {docset.title}", "", docset.overview, ""]
    graph = mermaid_graph(docset)
    if graph:
        out += ["## Component map", "", "```mermaid", graph, "```", ""]
    out += ["## Components", "", "| Component | Type | Applies to | Status | Updated by | Review notes |",
            "|---|---|---|---|---|---|"]
    for a in docset.artifacts:
        notes = sum(1 for f in a.analysis.findings if f.severity in ("high", "medium"))
        out.append(f"| [{a.name}](artifacts/{slugs[a.key]}.md) | {a.type_label} | {a.target or ''} | {_status(a)} | "
                   f"{a.updated_by or a.author} | {notes or ''} |")
    index = out_dir / "README.md"
    index.write_text("\n".join(out) + "\n", encoding="utf-8")
    return index
