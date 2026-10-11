"""SAP SuccessFactors adapter.

SuccessFactors development is mostly configuration: Business Rules, MDF
objects, Integration Center integrations and workflows. Export formats differ
between tenants and tools (Import and Export Data CSVs, OData API responses,
Check Tool / Integration Center exports), so this adapter reads:

* JSON - a list of records, an OData v2 response (``{"d": {"results": [...]}}``),
  or ``{"artifacts": [...]}``.
* CSV - one record per row.

Column/key names are resolved through ``FIELD_ALIASES`` and can be overridden
with a mapping file (``--mapping mapping.json``) so any tenant's export works.
Each record needs a type, given by a ``type`` column, ``--sf-type`` or the
file name (e.g. ``business_rules.csv``).
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..model import Artifact, Step
from .base import Adapter, register

TYPES = {
    "business_rule": "Business Rule",
    "mdf_object": "MDF Object Definition",
    "integration": "Integration Center Integration",
    "workflow": "Workflow",
    "picklist": "Picklist",
    "rbp_role": "Permission Role",
}

TYPE_HINTS = {  # file-name fragments -> type
    "rule": "business_rule", "mdf": "mdf_object", "object": "mdf_object",
    "integration": "integration", "workflow": "workflow", "picklist": "picklist", "role": "rbp_role",
}

# canonical field -> accepted keys in exports (first match wins, case-insensitive)
FIELD_ALIASES: Dict[str, List[str]] = {
    "type": ["type", "artifactType"],
    "id": ["id", "externalCode", "ruleId", "code", "objectCode", "integrationId", "workflowId"],
    "name": ["name", "ruleName", "externalName", "label", "integrationName", "objectName"],
    "description": ["description", "ruleDescription", "comment"],
    "base_object": ["baseObject", "base_object", "object", "baseEntity", "sourceEntity"],
    "scenario": ["scenario", "ruleScenario", "ruleType", "purpose"],
    "event": ["event", "eventType", "trigger", "ruleEvent"],
    "status": ["status", "effectiveStatus", "active"],
    "author": ["createdBy", "author", "created_by"],
    "updated_by": ["lastModifiedBy", "updated_by"],
    "updated_on": ["lastModifiedDateTime", "lastModifiedDate", "updated_on", "mdfSystemLastModifiedDate"],
    "conditions": ["conditions", "ruleDefinition", "statements", "rule"],
    "fields": ["fields", "fieldDefinitions"],
    "associations": ["associations"],
    "destination": ["destination", "destinationType", "target"],
    "schedule": ["schedule", "scheduling"],
    "mappings": ["mappings", "fieldMappings"],
    "filter": ["filter", "filters"],
    "steps": ["steps", "approvalSteps", "approvers"],
}


def _pick(record: Dict[str, Any], canonical: str, aliases: Dict[str, List[str]]) -> Any:
    lowered = {k.lower(): v for k, v in record.items()}
    for key in aliases.get(canonical, [canonical]):
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str) and value.strip()[:1] in ("[", "{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _rule_text(conditions: Any) -> (List[Step], str):
    """Turn rule conditions into ordered steps plus readable pseudo-code.

    Accepts ``[{"if": "...", "then": [...], "else": [...]}, ...]`` or free text.
    """
    if isinstance(conditions, str):
        lines = [ln.strip() for ln in re.split(r"[\n;]+", conditions) if ln.strip()]
        return [Step(order=i + 1, kind="statement", label=ln) for i, ln in enumerate(lines)], conditions
    steps: List[Step] = []
    text: List[str] = []
    for i, block in enumerate(conditions or [], start=1):
        if not isinstance(block, dict):
            steps.append(Step(order=i, kind="statement", label=str(block)))
            text.append(str(block))
            continue
        cond = block.get("if") or block.get("condition") or "Always"
        then = block.get("then") or []
        other = block.get("else") or []
        then = [then] if isinstance(then, str) else then
        other = [other] if isinstance(other, str) else other
        prefix = "IF" if i == 1 else "ELSE IF"
        text.append(f"{prefix} {cond}")
        text.extend(f"    THEN {t}" for t in then)
        if other:
            text.append("ELSE")
            text.extend(f"    {e}" for e in other)
        steps.append(Step(order=i, kind="condition", label=f"If {cond}",
                          detail="; ".join(then) + (f" | otherwise: {'; '.join(other)}" if other else "")))
    return steps, "\n".join(text)


@register
class SuccessFactorsAdapter(Adapter):
    platform = "successfactors"
    label = "SAP SuccessFactors"
    file_patterns = ("*.json", "*.csv")

    def __init__(self, mapping: Optional[str] = None, sf_type: Optional[str] = None, **options):
        super().__init__(**options)
        self.aliases = {k: list(v) for k, v in FIELD_ALIASES.items()}
        if mapping:
            for canonical, keys in json.loads(Path(mapping).read_text()).items():
                keys = [keys] if isinstance(keys, str) else keys
                self.aliases[canonical] = keys + self.aliases.get(canonical, [])
        self.sf_type = sf_type

    def load_file(self, path: Path) -> List[Artifact]:
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as fh:
                records = list(csv.DictReader(fh))
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data = data.get("d", data)
                data = data.get("results", data.get("artifacts", [data])) if isinstance(data, dict) else data
            records = data
        default_type = self.sf_type or next(
            (t for hint, t in TYPE_HINTS.items() if hint in path.stem.lower()), "business_rule")
        return [self._to_artifact(r, default_type, str(path)) for r in records if isinstance(r, dict)]

    def _to_artifact(self, record: Dict[str, Any], default_type: str, source: str) -> Artifact:
        get = lambda c: _maybe_json(_pick(record, c, self.aliases))  # noqa: E731
        atype = str(get("type") or default_type).strip().lower().replace(" ", "_")
        name = str(get("name") or get("id") or "unnamed")
        status = get("status")
        active = None if status is None else str(status).strip().lower() in ("a", "active", "true", "1", "yes")
        artifact = Artifact(
            platform=self.platform, type=atype, type_label=TYPES.get(atype, atype.replace("_", " ").title()),
            name=name, id=str(get("id") or name), target=str(get("base_object") or ""),
            description=str(get("description") or ""), author=str(get("author") or ""),
            updated_by=str(get("updated_by") or ""), updated_on=str(get("updated_on") or ""),
            active=active, source=source, language="rule",
        )
        if atype == "business_rule":
            artifact.trigger = {k: v for k, v in {"scenario": get("scenario"), "event": get("event"),
                                                  "base_object": get("base_object")}.items() if v}
            artifact.steps, text = _rule_text(get("conditions"))
            if text:
                artifact.scripts["Rule definition"] = text
        elif atype == "mdf_object":
            fields = get("fields") or []
            artifact.steps = [Step(order=i, kind="field", label=f.get("name", str(f)) if isinstance(f, dict) else str(f),
                                   detail=", ".join(f"{k}={v}" for k, v in f.items() if k != "name") if isinstance(f, dict) else "")
                              for i, f in enumerate(fields, start=1)]
            if get("associations"):
                artifact.properties["Associations"] = get("associations")
        elif atype == "integration":
            artifact.trigger = {k: v for k, v in {"schedule": get("schedule"), "filter": get("filter")}.items() if v}
            artifact.properties.update({k: v for k, v in {"Source entity": get("base_object"),
                                                          "Destination": get("destination")}.items() if v})
            mappings = get("mappings") or []
            artifact.steps = [Step(order=i, kind="mapping", label=f"{m.get('source', '?')} -> {m.get('target', '?')}",
                                   detail=m.get("transform", "")) if isinstance(m, dict)
                              else Step(order=i, kind="mapping", label=str(m))
                              for i, m in enumerate(mappings, start=1)]
        elif atype == "workflow":
            steps = get("steps") or []
            artifact.steps = [Step(order=i, kind="approval", label=s.get("approver", str(s)) if isinstance(s, dict) else str(s),
                                   detail=s.get("type", "") if isinstance(s, dict) else "")
                              for i, s in enumerate(steps, start=1)]
        known = {k.lower() for keys in self.aliases.values() for k in keys}
        for key, value in record.items():
            if key.lower() not in known and value not in (None, "") and not key.startswith("__"):
                artifact.properties.setdefault(key, value)
        return artifact
