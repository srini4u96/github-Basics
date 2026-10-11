"""Machine-readable output for publishing elsewhere (Confluence, ServiceNow KB, SharePoint, search...)."""
from __future__ import annotations

import json
from pathlib import Path

from ..model import DocumentationSet


def render(docset: DocumentationSet, out_dir: Path) -> Path:
    path = Path(out_dir) / "documentation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(docset.to_dict(), indent=2, default=str), encoding="utf-8")
    return path
