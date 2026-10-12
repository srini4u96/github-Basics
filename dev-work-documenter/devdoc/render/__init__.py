from pathlib import Path
from typing import Dict, Iterable

from ..model import DocumentationSet
from . import html, json_out, markdown

RENDERERS = {"md": markdown.render, "html": html.render, "json": json_out.render}


def render_all(docset: DocumentationSet, out_dir: Path, formats: Iterable[str]) -> Dict[str, Path]:
    unknown = set(formats) - set(RENDERERS)
    if unknown:
        raise ValueError(f"Unknown format(s): {', '.join(sorted(unknown))}. Use md, html, json.")
    return {fmt: RENDERERS[fmt](docset, Path(out_dir)) for fmt in formats}
