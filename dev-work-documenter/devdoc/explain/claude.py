"""Claude-powered explainer: narrative, step-by-step walkthroughs of each artifact.

Requires ``pip install anthropic`` and credentials (``ANTHROPIC_API_KEY`` or an
``ant auth login`` profile). The static-analysis facts are sent alongside the
code so the explanation stays grounded in what the tool actually found.
Note: this sends artifact source code to the Anthropic API.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Optional

import anthropic

from ..model import Artifact, DocumentationSet
from .base import Explainer
from .template import TemplateExplainer, summary_sentence

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You write developer handover documentation for enterprise platform work \
(ServiceNow, SAP SuccessFactors and similar). A teammate who did not build the component \
will read your walkthrough instead of asking the original developer, so explain it the way \
that developer would in a walkthrough session.

Write GitHub-flavoured Markdown with exactly these level-3 sections, in this order:
### Summary - two or three sentences: what it is and the business reason it exists.
### When it runs - the trigger, conditions, ordering, and who/what causes it.
### Walkthrough - walk through the logic in execution order as a numbered list, referring \
to function names, variables and fields in `code` formatting. Explain why, not just what.
### Data and side effects - tables/objects read and written, fields set, events fired, \
messages shown, external calls.
### Dependencies - other components it relies on or that rely on it.
### Things to watch - risks, edge cases, platform best-practice issues, and anything that \
looks unfinished. Use the static-analysis findings provided, confirm or correct them.
### How to test - concrete manual test steps a tester can follow.

Rules: base every statement on the supplied code and metadata; if something cannot be \
determined, say so instead of guessing. Do not repeat the whole source code. No preamble \
and no top-level heading."""

OVERVIEW_PROMPT = """Write the opening section of a handover document for the delivery described \
below. Use Markdown with these level-3 sections: ### What was built (business view, 1 paragraph), \
### How it works end to end (numbered flow across the components, naming each one in bold), \
### Where to start reading (entry points), ### Review hot spots. No preamble, no top-level heading."""


class ClaudeExplainer(Explainer):
    def __init__(self, model: Optional[str] = None, effort: str = "medium", workers: int = 4,
                 client: Optional[anthropic.Anthropic] = None, **_):
        self.model = model or DEFAULT_MODEL
        self.effort = effort
        self.workers = workers
        self.client = client or anthropic.Anthropic()
        self.fallback = TemplateExplainer()

    # ------------------------------------------------------------------ API
    def _ask(self, system: str, prompt: str) -> str:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            # Re-run on Anthropic's recommended model if a safety classifier declines.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("the model declined to explain this artifact")
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if response.stop_reason == "max_tokens":
            text += "\n\n_(Explanation truncated.)_"
        return text

    def explain_artifact(self, artifact: Artifact, docset: DocumentationSet) -> str:
        facts = {
            "platform": artifact.platform,
            "type": artifact.type_label,
            "name": artifact.name,
            "target": artifact.target,
            "application": artifact.application,
            "description": artifact.description,
            "active": artifact.active,
            "deleted": artifact.deleted,
            "trigger": artifact.trigger,
            "properties": artifact.properties,
            "steps": [asdict(s) for s in artifact.steps],
            "static_analysis": asdict(artifact.analysis),
            "connections": self.fallback.explain_artifact(artifact, docset).split("### Connections in this delivery")[-1]
            if any(artifact.key in (d.source, d.target) for d in docset.dependencies) else "none",
        }
        code = "\n\n".join(f"--- {label} ({artifact.language}) ---\n{src}" for label, src in artifact.scripts.items())
        prompt = (f"<metadata>\n{json.dumps(facts, indent=2, default=str)}\n</metadata>\n\n"
                  f"<source>\n{code or '(no code - declarative configuration only)'}\n</source>\n\n"
                  f"Write the walkthrough for this {artifact.type_label}.")
        try:
            return self._ask(SYSTEM_PROMPT, prompt)
        except (anthropic.APIError, RuntimeError) as exc:
            log.warning("Claude explanation failed for %s (%s); using offline explanation", artifact.name, exc)
            return self.fallback.explain_artifact(artifact, docset) + f"\n\n_AI explanation unavailable: {exc}_"

    def overview(self, docset: DocumentationSet) -> str:
        components = "\n\n".join(
            f"## {a.type_label}: {a.name}\n{summary_sentence(a)}\n\n{a.explanation}" for a in docset.artifacts)
        prompt = (f"<delivery_metadata>\n{json.dumps(docset.metadata, indent=2)}\n</delivery_metadata>\n\n"
                  f"<offline_overview>\n{self.fallback.overview(docset)}\n</offline_overview>\n\n"
                  f"<components>\n{components}\n</components>")
        try:
            return self._ask(OVERVIEW_PROMPT, prompt)
        except (anthropic.APIError, RuntimeError) as exc:
            log.warning("Claude overview failed (%s); using offline overview", exc)
            return self.fallback.overview(docset)

    def run(self, docset: DocumentationSet) -> DocumentationSet:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            texts = list(pool.map(lambda a: self.explain_artifact(a, docset), docset.artifacts))
        for artifact, text in zip(docset.artifacts, texts):
            artifact.explanation = text
        docset.overview = self.overview(docset)
        return docset
