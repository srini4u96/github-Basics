"""ServiceNow adapter.

Understands the formats ServiceNow developers already produce:

* Update set exports (``<unload>`` with ``sys_update_xml`` rows whose payload holds
  the record XML) - "Export to XML" on a local or retrieved update set.
* Single-record XML exports (``<unload><sys_script ...>``) - "Export > XML" on a form.
* Source-control / app repo files (``update/<table>_<sys_id>.xml`` with ``<record_update>``).

It can also pull an update set straight from an instance via the REST Table API
(see ``pull_update_set``).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:  # prefer the hardened parser when available
    from defusedxml import ElementTree as ET  # type: ignore
except ImportError:  # pragma: no cover - stdlib fallback
    import xml.etree.ElementTree as ET  # noqa: N817

from ..model import Artifact, Step
from .base import Adapter, register


def _truthy(value: Optional[str]) -> Optional[bool]:
    if value is None or value == "":
        return None
    return value.strip().lower() in ("true", "1", "yes")


# --------------------------------------------------------------------------- #
# Per-table mapping. To support another ServiceNow record type, add an entry.
#   type/label : canonical type + display label
#   name       : field(s) used as the artifact name (first non-empty wins)
#   target     : field holding the table the artifact runs against
#   scripts    : {display label: field}
#   trigger    : callable(fields) -> dict describing when it runs
#   props      : extra fields worth showing ({display label: field})
# --------------------------------------------------------------------------- #
def _br_trigger(f: Dict[str, str]) -> Dict[str, Any]:
    ops = [op for op in ("insert", "update", "delete", "query") if _truthy(f.get(f"action_{op}"))]
    return {
        "when": f.get("when", ""),
        "operations": ops,
        "order": f.get("order", ""),
        "condition": f.get("condition", ""),
        "filter_condition": f.get("filter_condition", ""),
    }


TABLE_SPECS: Dict[str, Dict[str, Any]] = {
    "sys_script": {
        "type": "business_rule", "label": "Business Rule", "name": ["name"], "target": "collection",
        "scripts": {"Script": "script"}, "trigger": _br_trigger,
        "props": {"Advanced": "advanced", "Abort action": "abort_action"},
    },
    "sys_script_include": {
        "type": "script_include", "label": "Script Include", "name": ["name", "api_name"],
        "scripts": {"Script": "script"},
        "trigger": lambda f: {"invoked": "called from other server scripts"
                              + (" and from the browser via GlideAjax" if _truthy(f.get("client_callable")) else "")},
        "props": {"API name": "api_name", "Client callable": "client_callable", "Accessible from": "access"},
    },
    "sys_script_client": {
        "type": "client_script", "label": "Client Script", "name": ["name"], "target": "table",
        "scripts": {"Script": "script"},
        "trigger": lambda f: {"type": f.get("type", ""), "field": f.get("field_name", ""),
                              "ui_type": {"0": "Desktop", "1": "Mobile / Service Portal", "10": "All"}.get(f.get("ui_type", ""), f.get("ui_type", ""))},
        "props": {"Isolate script": "isolate_script"},
    },
    "catalog_script_client": {
        "type": "catalog_client_script", "label": "Catalog Client Script", "name": ["name"],
        "target": "cat_item", "scripts": {"Script": "script"},
        "trigger": lambda f: {"type": f.get("type", ""), "variable": f.get("cat_variable", "")},
    },
    "sys_ui_action": {
        "type": "ui_action", "label": "UI Action", "name": ["name"], "target": "table",
        "scripts": {"Script": "script"},
        "trigger": lambda f: {"shown_as": [k for k, fld in (("Form button", "form_button"), ("Form link", "form_link"),
                                                           ("List button", "list_button"), ("Context menu", "form_context_menu"))
                                           if _truthy(f.get(fld))],
                              "condition": f.get("condition", ""),
                              "runs_on_client": f.get("client", "") , "onclick": f.get("onclick", "")},
        "props": {"Action name": "action_name"},
    },
    "sys_ui_policy": {
        "type": "ui_policy", "label": "UI Policy", "name": ["short_description"], "target": "table",
        "scripts": {"Execute if true": "script_true", "Execute if false": "script_false"},
        "trigger": lambda f: {"conditions": f.get("conditions", ""), "on_load": f.get("on_load", ""),
                              "reverse_if_false": f.get("reverse_if_false", "")},
    },
    "sysauto_script": {
        "type": "scheduled_job", "label": "Scheduled Script Execution", "name": ["name"],
        "scripts": {"Script": "script"},
        "trigger": lambda f: {"run": f.get("run_type", ""), "time": f.get("run_time", ""),
                              "period": f.get("run_period", ""), "day": f.get("run_dayofweek", "")},
    },
    "sysevent_script_action": {
        "type": "script_action", "label": "Script Action", "name": ["name"],
        "scripts": {"Script": "script"},
        "trigger": lambda f: {"event": f.get("event_name", ""), "condition": f.get("condition_script", "")},
    },
    "sysevent_email_action": {
        "type": "notification", "label": "Notification", "name": ["name"], "target": "collection",
        "scripts": {"Advanced condition": "advanced_condition"},
        "trigger": lambda f: {"event": f.get("event_name", ""), "on_insert": f.get("action_insert", ""),
                              "on_update": f.get("action_update", ""), "condition": f.get("condition", "")},
        "props": {"Subject": "subject", "Recipients (fields)": "recipient_fields", "Recipient groups": "recipient_groups"},
        "language": "text",
    },
    "sys_ws_operation": {
        "type": "scripted_rest", "label": "Scripted REST Resource", "name": ["name"],
        "scripts": {"Script": "operation_script"},
        "trigger": lambda f: {"method": f.get("http_method", ""), "path": f.get("operation_uri", "") or f.get("relative_path", ""),
                              "api": f.get("web_service_definition", "")},
    },
    "sys_script_fix": {
        "type": "fix_script", "label": "Fix Script", "name": ["name"], "scripts": {"Script": "script"},
        "trigger": lambda f: {"invoked": "Run once, manually or on application install"},
    },
    "sys_security_acl": {
        "type": "acl", "label": "Access Control (ACL)", "name": ["name"], "scripts": {"Script": "script"},
        "trigger": lambda f: {"operation": f.get("operation", ""), "type": f.get("type", ""), "condition": f.get("condition", "")},
        "props": {"Admin overrides": "admin_overrides"},
    },
    "sys_hub_flow": {
        "type": "flow", "label": "Flow Designer", "name": ["name"], "scripts": {},
        "trigger": lambda f: {},
        "props": {"Flow type": "type", "Run as": "run_as", "Flow status": "status", "Internal name": "internal_name"},
        "language": "flow",
    },
    "sys_hub_action_type_definition": {
        "type": "flow_action", "label": "Flow Designer Action", "name": ["name"], "scripts": {},
        "trigger": lambda f: {"invoked": "Used as a step inside flows/subflows"},
        "props": {"Category": "category", "Internal name": "internal_name"}, "language": "flow",
    },
    "sys_db_object": {
        "type": "table", "label": "Table", "name": ["label", "name"], "scripts": {},
        "trigger": lambda f: {},
        "props": {"Table name": "name", "Extends": "super_class", "Accessible from": "access"},
        "language": "text",
    },
    "sys_dictionary": {
        "type": "dictionary", "label": "Field (Dictionary)", "name": ["element"], "target": "name",
        "scripts": {"Calculation": "calculation", "Default value": "default_value"},
        "trigger": lambda f: {},
        "props": {"Label": "column_label", "Type": "internal_type", "Reference": "reference",
                  "Mandatory": "mandatory", "Max length": "max_length"},
    },
    "sys_properties": {
        "type": "system_property", "label": "System Property", "name": ["name"], "scripts": {},
        "trigger": lambda f: {}, "props": {"Value": "value", "Type": "type"}, "language": "text",
    },
}

# Flow Designer stores a flow as several records that point at the parent flow.
FLOW_CHILD_TABLES = {
    "sys_hub_trigger_instance": "trigger", "sys_hub_trigger_instance_v2": "trigger",
    "sys_hub_action_instance": "action", "sys_hub_action_instance_v2": "action",
    "sys_hub_sub_flow_instance": "subflow", "sys_hub_sub_flow_instance_v2": "subflow",
    "sys_hub_flow_logic": "logic", "sys_hub_flow_logic_instance_v2": "logic",
}

# Records that are noise for a walkthrough (metadata, translations, etc.)
IGNORED_TABLES = {"sys_remote_update_set", "sys_update_set", "sys_app", "sys_metadata_link",
                  "sys_translated_text", "sys_documentation", "sys_choice", "sys_ui_section",
                  "sys_ui_element", "sys_ui_list", "sys_ui_list_element", "sys_hub_flow_snapshot",
                  "sys_variable_value", "sys_element_mapping", "sys_hub_flow_input", "sys_hub_flow_output",
                  "sys_hub_pill_compound", "sys_hub_flow_variable", "sys_flow_context"}


def _record_fields(elem) -> Dict[str, str]:
    """Flatten a record element. Reference fields prefer their display value."""
    out: Dict[str, str] = {}
    for child in elem:
        display = child.get("display_value")
        out[child.tag] = (display or child.text or "").strip()
        if display:
            out[f"{child.tag}.sys_id"] = (child.text or "").strip()
    return out


@register
class ServiceNowAdapter(Adapter):
    platform = "servicenow"
    label = "ServiceNow"
    file_patterns = ("*.xml",)

    def __init__(self, **options):
        super().__init__(**options)
        self._meta: Dict[str, str] = {}
        self._flow_children: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ load
    def load(self, paths):
        self._flow_children = []
        artifacts = super().load(paths)
        self._attach_flow_children(artifacts)
        return sorted(artifacts, key=lambda a: (a.type, a.name.lower()))

    def load_file(self, path: Path) -> List[Artifact]:
        root = ET.parse(str(path)).getroot()
        records = []  # (table, element, action)
        if root.tag == "record_update":
            records.extend(self._records_in(root))
        else:
            for child in root:
                if child.tag == "sys_remote_update_set" or child.tag == "sys_update_set":
                    f = _record_fields(child)
                    self._meta.setdefault("update_set", f.get("name", ""))
                    self._meta.setdefault("update_set_description", f.get("description", ""))
                    self._meta.setdefault("application", f.get("application_name", "") or f.get("application", ""))
                    self._meta.setdefault("released_by", f.get("sys_created_by", ""))
                elif child.tag == "sys_update_xml":
                    payload = child.findtext("payload") or ""
                    action = (child.findtext("action") or "").upper()
                    if not payload.strip():
                        continue
                    inner = ET.fromstring(payload.encode("utf-8"))
                    for table, elem, rec_action in self._records_in(inner):
                        records.append((table, elem, "DELETE" if action == "DELETE" else rec_action))
                else:
                    records.append((child.tag, child, (child.get("action") or "").upper()))

        artifacts = []
        for table, elem, action in records:
            artifact = self._to_artifact(table, elem, action, str(path))
            if artifact:
                artifacts.append(artifact)
        return artifacts

    @staticmethod
    def _records_in(record_update):
        if record_update.tag != "record_update":
            yield record_update.tag, record_update, (record_update.get("action") or "").upper()
            return
        for elem in record_update:
            yield elem.tag, elem, (elem.get("action") or "").upper()

    def _to_artifact(self, table: str, elem, action: str, source: str) -> Optional[Artifact]:
        if table in IGNORED_TABLES:
            return None
        fields = _record_fields(elem)
        if table in FLOW_CHILD_TABLES:
            self._flow_children.append({"kind": FLOW_CHILD_TABLES[table], **fields})
            return None

        spec = TABLE_SPECS.get(table)
        if spec is None:
            spec = self._generic_spec(table, fields)
        name = next((fields.get(n) for n in spec["name"] if fields.get(n)), "") or fields.get("sys_id", "unnamed")
        trigger_fn: Callable = spec.get("trigger") or (lambda f: {})
        props = {label: fields[fld] for label, fld in spec.get("props", {}).items() if fields.get(fld)}
        return Artifact(
            platform=self.platform,
            type=spec["type"],
            type_label=spec["label"],
            name=name,
            id=fields.get("sys_id", name),
            application=fields.get("sys_scope", "") or self._meta.get("application", ""),
            target=fields.get(spec.get("target", ""), "") if spec.get("target") else "",
            description=self._description(spec, fields),
            author=fields.get("sys_created_by", ""),
            updated_by=fields.get("sys_updated_by", ""),
            updated_on=fields.get("sys_updated_on", ""),
            active=_truthy(fields.get("active")),
            deleted=action == "DELETE",
            trigger={k: v for k, v in trigger_fn(fields).items() if v not in ("", [], None)},
            scripts={label: fields[fld] for label, fld in spec.get("scripts", {}).items() if fields.get(fld, "").strip()},
            language=spec.get("language", "javascript"),
            properties={**props, "Record type": table},
            source=source,
        )

    @staticmethod
    def _description(spec: Dict[str, Any], fields: Dict[str, str]) -> str:
        if "short_description" in spec["name"]:  # already used as the name
            return fields.get("description", "")
        return fields.get("description", "") or fields.get("short_description", "")

    @staticmethod
    def _generic_spec(table: str, fields: Dict[str, str]) -> Dict[str, Any]:
        """Best effort for record types without a mapping: keep any script-like field."""
        scripts = {k: k for k in fields if "script" in k and not k.endswith(".sys_id")}
        return {"type": table, "label": table, "name": ["name", "short_description", "label", "sys_name"],
                "scripts": scripts, "target": "table" if "table" in fields else "collection"}

    def _attach_flow_children(self, artifacts: List[Artifact]) -> None:
        flows = {a.id: a for a in artifacts if a.type == "flow"}
        flows_by_name = {a.name: a for a in flows.values()}
        for child in self._flow_children:
            flow = flows.get(child.get("flow.sys_id", "")) or flows.get(child.get("flow", "")) \
                or flows_by_name.get(child.get("flow", ""))
            if not flow:
                continue
            kind = child["kind"]
            if kind == "trigger":
                flow.trigger = {k: v for k, v in {
                    "type": child.get("trigger_type", "") or child.get("trigger_definition", ""),
                    "table": child.get("table", ""),
                    "condition": child.get("condition", ""),
                    "schedule": child.get("schedule", "") or child.get("run_time", ""),
                }.items() if v}
                if child.get("table"):
                    flow.target = child["table"]
                continue
            label = (child.get("action_type") or child.get("sub_flow") or child.get("logic_definition")
                     or child.get("name") or kind)
            try:
                order = int(child.get("order") or 0)
            except ValueError:
                order = 0
            flow.steps.append(Step(order=order, kind=kind, label=label, detail=child.get("comment", "")))
        for flow in flows.values():
            flow.steps.sort(key=lambda s: s.order)

    def metadata(self) -> Dict[str, str]:
        return {k: v for k, v in self._meta.items() if v}


# ---------------------------------------------------------------------------
# Pulling directly from an instance
# ---------------------------------------------------------------------------
def _get_json(url: str, user: str, password: str) -> Dict[str, Any]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(url, headers={"Accept": "application/json", "Authorization": f"Basic {token}"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - URL is user-configured
        return json.load(response)


def pull_update_set(instance: str, update_set: str, output: Path,
                    user: Optional[str] = None, password: Optional[str] = None) -> Path:
    """Download every customer update in an update set into an XML file this adapter reads.

    ``update_set`` may be a name or a sys_id. Credentials default to the
    ``SN_USER`` / ``SN_PASSWORD`` environment variables; use a read-only
    integration account with access to ``sys_update_set`` and ``sys_update_xml``.
    """
    user = user or os.environ.get("SN_USER", "")
    password = password or os.environ.get("SN_PASSWORD", "")
    if not user or not password:
        raise ValueError("Set SN_USER and SN_PASSWORD (or pass user/password) to pull from an instance.")
    base = instance.rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"

    query = f"sys_id={update_set}^ORname={update_set}"
    sets = _get_json(f"{base}/api/now/table/sys_update_set?" + urllib.parse.urlencode(
        {"sysparm_query": query, "sysparm_fields": "sys_id,name,description,application,sys_created_by",
         "sysparm_display_value": "true", "sysparm_limit": "1"}), user, password)["result"]
    if not sets:
        raise ValueError(f"Update set '{update_set}' not found on {base}")
    us = sets[0]

    rows, offset, page = [], 0, 200
    while True:
        batch = _get_json(f"{base}/api/now/table/sys_update_xml?" + urllib.parse.urlencode(
            {"sysparm_query": f"update_set={us['sys_id']}^ORDERBYsys_updated_on",
             "sysparm_fields": "name,action,type,payload", "sysparm_limit": str(page),
             "sysparm_offset": str(offset)}), user, password)["result"]
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page

    import xml.etree.ElementTree as StdET  # writing only

    unload = StdET.Element("unload")
    header = StdET.SubElement(unload, "sys_remote_update_set")
    for key in ("name", "description", "sys_created_by"):
        StdET.SubElement(header, key).text = us.get(key, "")
    app = us.get("application")
    StdET.SubElement(header, "application_name").text = app.get("display_value", "") if isinstance(app, dict) else (app or "")
    for row in rows:
        rec = StdET.SubElement(unload, "sys_update_xml")
        for key in ("name", "action", "type", "payload"):
            StdET.SubElement(rec, key).text = row.get(key, "")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    StdET.ElementTree(unload).write(output, encoding="utf-8", xml_declaration=True)
    return output
