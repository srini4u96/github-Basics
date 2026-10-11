from __future__ import annotations

import re
from typing import Dict

from ..model import DocumentationSet


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "item"


def artifact_slugs(docset: DocumentationSet) -> Dict[str, str]:
    """Stable, unique file/anchor names per artifact."""
    out, used = {}, set()
    for a in docset.artifacts:
        base = slug(f"{a.type}-{a.name}")
        name, i = base, 2
        while name in used:
            name, i = f"{base}-{i}", i + 1
        used.add(name)
        out[a.key] = name
    return out


def mermaid_graph(docset: DocumentationSet) -> str:
    """Dependency diagram. Only artifacts that take part in a dependency are drawn."""
    if not docset.dependencies:
        return ""
    keys = docset.by_key()
    involved = [a for a in docset.artifacts
                if any(a.key in (d.source, d.target) for d in docset.dependencies)]
    ids = {a.key: f"n{i}" for i, a in enumerate(involved)}
    clean = lambda s: re.sub(r'["<>{}|\[\]]', "'", s)  # noqa: E731
    lines = ["flowchart LR"]
    for a in involved:
        lines.append(f'    {ids[a.key]}["{clean(a.name)}<br/><small>{clean(a.type_label)}</small>"]')
    for d in docset.dependencies:
        if d.source in ids and d.target in ids and d.source in keys:
            lines.append(f'    {ids[d.source]} -->|"{clean(d.reason)}"| {ids[d.target]}')
    return "\n".join(lines)
