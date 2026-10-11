"""Single self-contained HTML handbook (easy to email, attach to a story, or host)."""
from __future__ import annotations

import html
import re
from collections import defaultdict
from pathlib import Path
from typing import List

from ..model import Artifact, DocumentationSet
from .common import artifact_slugs, mermaid_graph
from .markdown import _status


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])_([^_]+)_(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', text)
    return text


def md_to_html(md: str) -> str:
    """Small Markdown subset: headings, lists, quotes, code fences, tables, paragraphs."""
    out: List[str] = []
    lines = (md or "").splitlines()
    i, para, list_tag = 0, [], None

    def flush_para():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para(); close_list()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i]); i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
        elif m := re.match(r"^(#{1,6})\s+(.*)", stripped):
            flush_para(); close_list()
            level = min(len(m.group(1)) + 1, 6)  # page already owns h1/h2
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
        elif m := re.match(r"^(?:[-*]|(\d+)\.)\s+(.*)", stripped):
            flush_para()
            tag = "ol" if m.group(1) else "ul"
            if list_tag != tag:
                close_list(); out.append(f"<{tag}>"); list_tag = tag
            out.append(f"<li>{_inline(m.group(2))}</li>")
        elif stripped.startswith(">"):
            flush_para(); close_list()
            out.append(f"<blockquote>{_inline(stripped.lstrip('> '))}</blockquote>")
        elif stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip()):
            flush_para(); close_list()
            cells = lambda row: [c.strip() for c in row.strip().strip("|").split("|")]  # noqa: E731
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells(line)) + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells(lines[i])) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue
        elif not stripped:
            flush_para(); close_list()
        else:
            close_list(); para.append(stripped)
        i += 1
    flush_para(); close_list()
    return "\n".join(out)


def _artifact_section(a: Artifact, anchor: str) -> str:
    rows = [("Type", a.type_label), ("Applies to", a.target), ("Application", a.application), ("Status", _status(a)),
            ("Created by", a.author), ("Last updated", " by ".join(x for x in (a.updated_on, a.updated_by) if x))]
    rows += [(k, v) for k, v in a.properties.items()]
    rows += [(f"Trigger · {k}", ", ".join(map(str, v)) if isinstance(v, list) else v) for k, v in a.trigger.items()]
    meta = "".join(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>" for k, v in rows if v)
    severities = sorted({f.severity for f in a.analysis.findings if f.severity in ("high", "medium")})
    badges = "".join(f'<span class="badge {s}">{s}</span>' for s in severities)
    code = "".join(
        f"<details><summary>{html.escape(label)} · {len(src.splitlines())} lines</summary>"
        f"<pre><code>{html.escape(src)}</code></pre></details>" for label, src in a.scripts.items())
    return (f'<section id="{anchor}" class="artifact"><h2>{html.escape(a.name)} {badges}</h2>'
            f'<p class="kind">{html.escape(a.type_label)}{" · " + html.escape(a.target) if a.target else ""}</p>'
            f'<table class="meta">{meta}</table>'
            f'<div class="explain">{md_to_html(a.explanation)}</div>{code}</section>')


CSS = """
:root{--bg:#fbfbfa;--panel:#fff;--fg:#1d1d1f;--muted:#6b6b70;--line:#e4e4e7;--accent:#2f5bd3;--code:#f3f3f5;
--high:#c62828;--medium:#b45f06}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#141416;--panel:#1c1c1f;--fg:#ececef;--muted:#9a9aa2;
--line:#2c2c31;--accent:#8ab0ff;--code:#232328;--high:#ff7b72;--medium:#f0b45a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}
.layout{display:grid;grid-template-columns:280px minmax(0,1fr);min-height:100vh}
nav{border-right:1px solid var(--line);padding:20px 16px;position:sticky;top:0;height:100vh;overflow:auto;background:var(--panel)}
nav h1{font-size:16px;margin:0 0 12px}nav input{width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:6px;
background:var(--bg);color:var(--fg);margin-bottom:12px}nav h3{font-size:11px;text-transform:uppercase;letter-spacing:.06em;
color:var(--muted);margin:16px 0 4px}nav a{display:block;color:var(--fg);text-decoration:none;padding:3px 6px;border-radius:4px;
font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}nav a:hover{background:var(--code)}
main{padding:32px clamp(16px,4vw,56px);max-width:1000px;min-width:0}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:20px 24px;margin:0 0 24px}
h2{margin:0 0 4px;font-size:20px}.kind{color:var(--muted);margin:0 0 12px}
code{overflow-wrap:anywhere;background:var(--code);padding:1px 5px;border-radius:4px;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
pre{background:var(--code);padding:14px;border-radius:8px;overflow:auto}pre code{padding:0;background:none;overflow-wrap:normal}
table{border-collapse:collapse;width:100%;display:block;overflow-x:auto;margin:8px 0 16px;font-size:14px}th,td{text-align:left;padding:6px 8px;
border-bottom:1px solid var(--line);vertical-align:top}table.meta th{width:180px;color:var(--muted);font-weight:500}
details{margin-top:8px}summary{cursor:pointer;color:var(--accent)}blockquote{border-left:3px solid var(--line);margin:8px 0;
padding:2px 12px;color:var(--muted)}.badge{font-size:11px;padding:2px 7px;border-radius:999px;border:1px solid;vertical-align:middle}
.badge.high{color:var(--high)}.badge.medium{color:var(--medium)}.mermaid{background:#fff;border-radius:8px;padding:8px;overflow:auto}
a{color:var(--accent)}
@media (max-width:800px){.layout{grid-template-columns:minmax(0,1fr)}nav{position:static;height:auto;max-height:45vh;border-right:0;border-bottom:1px solid var(--line)}section{padding:16px}table.meta th{width:auto}}
"""

SCRIPT = """
document.getElementById('q').addEventListener('input',e=>{const q=e.target.value.toLowerCase();
document.querySelectorAll('nav a[data-name]').forEach(a=>{a.style.display=a.dataset.name.includes(q)?'':'none'})});
"""


def render(docset: DocumentationSet, out_dir: Path) -> Path:
    slugs = artifact_slugs(docset)
    groups = defaultdict(list)
    for a in docset.artifacts:
        groups[a.type_label].append(a)
    nav = "".join(
        f"<h3>{html.escape(label)} ({len(items)})</h3>" + "".join(
            f'<a href="#{slugs[a.key]}" data-name="{html.escape(a.name.lower())}">{html.escape(a.name)}</a>' for a in items)
        for label, items in sorted(groups.items()))
    graph = mermaid_graph(docset)
    graph_html = (f'<section><h2>Component map</h2><pre class="mermaid">{html.escape(graph)}</pre></section>'
                  if graph else "")
    rows = "".join(
        f'<tr><td><a href="#{slugs[a.key]}">{html.escape(a.name)}</a></td><td>{html.escape(a.type_label)}</td>'
        f"<td>{html.escape(a.target)}</td><td>{_status(a)}</td><td>{html.escape(a.updated_by or a.author)}</td></tr>"
        for a in docset.artifacts)
    body = (f'<div class="layout"><nav><h1>{html.escape(docset.title)}</h1>'
            f'<input id="q" placeholder="Filter components…" aria-label="Filter components">'
            f'<a href="#overview">Overview</a>{nav}</nav><main>'
            f'<section id="overview"><h2>{html.escape(docset.title)}</h2>{md_to_html(docset.overview)}</section>'
            f"{graph_html}<section><h2>Components</h2><table><thead><tr><th>Component</th><th>Type</th>"
            f"<th>Applies to</th><th>Status</th><th>Updated by</th></tr></thead><tbody>{rows}</tbody></table></section>"
            + "".join(_artifact_section(a, slugs[a.key]) for a in docset.artifacts) + "</main></div>")
    mermaid = ('<script type="module">import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs";'
               'mermaid.initialize({startOnLoad:true,theme:"neutral"});</script>' if graph else "")
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{html.escape(docset.title)}</title><style>{CSS}</style></head>"
            f"<body>{body}<script>{SCRIPT}</script>{mermaid}</body></html>")
    path = Path(out_dir) / "documentation.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
