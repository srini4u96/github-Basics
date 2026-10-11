"""Platform-neutral model for development artifacts.

Every platform adapter (ServiceNow, SuccessFactors, ...) converts its native
export format into these objects. Analyzers, explainers and renderers only
ever see this model, which is what makes the solution reusable across
platforms.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


@dataclass
class Finding:
    """A review note produced by static analysis (risk, smell, best practice)."""

    severity: str  # high | medium | low | info
    message: str
    rule: str = ""


@dataclass
class Analysis:
    """Facts extracted from an artifact's code/configuration."""

    tables_read: List[str] = field(default_factory=list)
    tables_written: List[str] = field(default_factory=list)
    fields_set: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)  # names of other components it calls
    events_fired: List[str] = field(default_factory=list)
    properties_used: List[str] = field(default_factory=list)
    integrations: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    behaviours: List[str] = field(default_factory=list)  # e.g. "Aborts the transaction"
    findings: List[Finding] = field(default_factory=list)
    lines_of_code: int = 0
    complexity: int = 0


@dataclass
class Step:
    """An ordered step of a declarative artifact (flow action, rule statement...)."""

    order: int
    kind: str
    label: str
    detail: str = ""


@dataclass
class Artifact:
    platform: str  # "servicenow", "successfactors", ...
    type: str  # canonical key, e.g. "business_rule"
    type_label: str  # human label, e.g. "Business Rule"
    name: str
    id: str
    application: str = ""
    target: str = ""  # table / base object the artifact is bound to
    description: str = ""
    author: str = ""
    updated_by: str = ""
    updated_on: str = ""
    active: Optional[bool] = None
    deleted: bool = False
    trigger: Dict[str, Any] = field(default_factory=dict)  # when it runs
    scripts: Dict[str, str] = field(default_factory=dict)  # label -> source
    language: str = "javascript"
    steps: List[Step] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)  # other config worth showing
    source: str = ""  # file / update set it came from
    analysis: Analysis = field(default_factory=Analysis)
    explanation: str = ""  # Markdown walkthrough written by an explainer

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.type}:{self.id}"

    @property
    def all_code(self) -> str:
        return "\n\n".join(code for code in self.scripts.values() if code)


@dataclass
class Dependency:
    source: str  # artifact key
    target: str  # artifact key
    reason: str


@dataclass
class DocumentationSet:
    """Everything delivered in one piece of work (update set, release, sprint...)."""

    title: str
    platform: str
    artifacts: List[Artifact] = field(default_factory=list)
    dependencies: List[Dependency] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)  # e.g. update set name, author
    overview: str = ""  # Markdown overview written by an explainer

    def by_key(self) -> Dict[str, Artifact]:
        return {a.key: a for a in self.artifacts}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
