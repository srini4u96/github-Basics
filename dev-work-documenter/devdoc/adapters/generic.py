"""Generic adapter: artifacts already described in the neutral JSON shape.

Lets any platform (Salesforce, Workday, SAP BTP, custom apps...) use the
documentation pipeline without writing Python - export or hand-write a file:

    {"platform": "salesforce",
     "artifacts": [{"type": "apex_trigger", "type_label": "Apex Trigger",
                    "name": "AccountTrigger", "target": "Account",
                    "trigger": {"when": "before insert"},
                    "scripts": {"Body": "trigger AccountTrigger on Account ..."},
                    "language": "apex"}]}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from ..model import Artifact, Step
from .base import Adapter, register

_FIELDS = set(Artifact.__dataclass_fields__) - {"analysis", "explanation", "steps", "platform"}


@register
class GenericAdapter(Adapter):
    platform = "generic"
    label = "Generic (neutral JSON)"
    file_patterns = ("*.json",)

    def load_file(self, path: Path) -> List[Artifact]:
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data.get("artifacts", []) if isinstance(data, dict) else data
        platform = data.get("platform", "generic") if isinstance(data, dict) else "generic"
        artifacts = []
        for rec in records:
            kwargs = {k: v for k, v in rec.items() if k in _FIELDS}
            kwargs.setdefault("type", "component")
            kwargs.setdefault("type_label", kwargs["type"].replace("_", " ").title())
            kwargs.setdefault("id", kwargs.get("name", "unnamed"))
            kwargs.setdefault("name", kwargs["id"])
            kwargs.setdefault("source", str(path))
            steps = [Step(order=s.get("order", i), kind=s.get("kind", "step"), label=s.get("label", ""),
                          detail=s.get("detail", "")) for i, s in enumerate(rec.get("steps", []), start=1)]
            artifacts.append(Artifact(platform=rec.get("platform", platform), steps=steps, **kwargs))
        return artifacts
