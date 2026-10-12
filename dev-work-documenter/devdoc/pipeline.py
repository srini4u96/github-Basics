"""load (adapter) -> analyze -> explain -> render."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional

from .adapters import get_adapter
from .analyzers import analyze
from .explain import get_explainer
from .model import DocumentationSet
from .render import render_all


def build_documentation(platform: str, inputs: Iterable[Path], out_dir: Optional[Path] = None,
                        formats: Iterable[str] = ("md", "html"), explainer: str = "template",
                        title: Optional[str] = None, include_types: Optional[Iterable[str]] = None,
                        adapter_options: Optional[Dict] = None,
                        explainer_options: Optional[Dict] = None) -> DocumentationSet:
    adapter = get_adapter(platform, **(adapter_options or {}))
    artifacts = adapter.load([Path(p) for p in inputs])
    if include_types:
        wanted = set(include_types)
        artifacts = [a for a in artifacts if a.type in wanted]
    meta = adapter.metadata()
    docset = DocumentationSet(
        title=title or meta.get("update_set") or f"{adapter.label} development work",
        platform=platform, artifacts=artifacts, metadata=meta)
    analyze(docset)
    get_explainer(explainer, **(explainer_options or {})).run(docset)
    if out_dir:
        render_all(docset, Path(out_dir), formats)
    return docset
