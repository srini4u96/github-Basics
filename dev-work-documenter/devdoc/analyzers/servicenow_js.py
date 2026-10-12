"""Static analysis for ServiceNow server/client JavaScript.

Regex based on purpose: it has to cope with partial snippets, ES5 and
ServiceNow-specific globals, and it only needs to surface facts a reviewer
would look for, not to prove anything.
"""
from __future__ import annotations

import re
from ..model import Analysis, Artifact, Finding
from .common import add_unique, code_metrics, strip_comments

GLIDE_QUERY = re.compile(r"(?:var|let|const)?\s*(\w+)\s*=\s*new\s+(?:global\.)?(GlideRecord(?:Secure)?|GlideAggregate)\s*\(\s*['\"]([\w.]+)['\"]")
GLIDE_INLINE = re.compile(r"new\s+(?:global\.)?(?:GlideRecord(?:Secure)?|GlideAggregate)\s*\(\s*['\"]([\w.]+)['\"]")
WRITE_CALL = r"\b{var}\s*\.\s*(insert|update|updateMultiple|deleteRecord|deleteMultiple|initialize)\s*\("
NEW_CLASS = re.compile(r"new\s+((?:[a-z]\w*\.)?[A-Z]\w*)\s*\(")
STATIC_CALL = re.compile(r"\b([A-Z]\w+)\s*\.\s*\w+\s*\(")
GLIDE_AJAX = re.compile(r"new\s+GlideAjax\s*\(\s*['\"]([\w.]+)['\"]")
EVENT = re.compile(r"gs\s*\.\s*eventQueue(?:Scheduled)?\s*\(\s*['\"]([\w.\-]+)['\"]")
PROPERTY = re.compile(r"gs\s*\.\s*getProperty\s*\(\s*['\"]([\w.\-]+)['\"]")
REST = re.compile(r"new\s+sn_ws\.(RESTMessageV2|SOAPMessageV2)\s*\(\s*(?:['\"]([^'\"]*)['\"])?")
FLOW_API = re.compile(r"sn_fd\.FlowAPI\s*\.\s*\w+\s*\(\s*['\"]([\w.]+)['\"]")
FUNC_DECL = re.compile(r"function\s+(\w+)\s*\(")
FUNC_PROP = re.compile(r"(\w+)\s*:\s*function\s*\(")
FIELD_SET = re.compile(r"\bcurrent\s*\.\s*(?:(\w+)\s*=(?!=)|setValue\s*\(\s*['\"](\w+)['\"])")
CLIENT_FIELD_SET = re.compile(r"g_form\s*\.\s*setValue\s*\(\s*['\"](\w+)['\"]")
SYS_ID = re.compile(r"(?<![0-9a-zA-Z_])[0-9a-f]{32}(?![0-9a-zA-Z_])")

# Globals / built-ins that look like classes but are not dependencies.
NOT_DEPENDENCIES = {
    "GlideRecord", "GlideRecordSecure", "GlideAggregate", "GlideAjax", "GlideDateTime", "GlideDate",
    "GlideDuration", "GlideSysAttachment", "GlideElement", "GlideSchedule", "GlideFilter", "GlideEmailOutbound",
    "GlideSystem", "GlideUser", "GlideDialogWindow", "GlideModal", "GlideList2", "GlideQuery", "GlideStringUtil",
    "GlideTableHierarchy", "GlideScopedEvaluator", "GlideImpersonate", "GlideSecureRandomUtil", "GlideDBFunctionBuilder",
    "Class", "Object", "Array", "JSON", "Math", "Date", "String", "Number", "RegExp", "Error", "Packages",
    "AbstractAjaxProcessor", "XMLDocument2", "XMLHelper", "Workflow", "JSUtil", "ArrayUtil", "TableUtils",
    "RESTMessageV2", "SOAPMessageV2", "GlideHTTPRequest", "GlideEncrypter", "GlideDigest", "GlideCalendarDateTime",
}

# Wrapper functions every script of a given type has; listing them adds nothing.
BOILERPLATE_FUNCTIONS = {"initialize", "type", "executeRule", "onLoad", "onChange", "onSubmit", "onCellEdit",
                         "onClick", "process", "runClientCode", "onCondition"}


def analyze(artifact: Artifact) -> Analysis:
    a = Analysis()
    code = strip_comments(artifact.all_code)
    if not code.strip():
        return a
    a.lines_of_code, a.complexity = code_metrics(code)
    client_side = artifact.type in ("client_script", "catalog_client_script", "ui_policy") or (
        artifact.type == "ui_action" and str(artifact.trigger.get("runs_on_client", "")).lower() == "true")

    for var, _cls, table in GLIDE_QUERY.findall(code):
        writes = re.findall(WRITE_CALL.format(var=re.escape(var)), code)
        if any(w != "initialize" for w in writes):
            add_unique(a.tables_written, table)
        if not writes or re.search(rf"\b{re.escape(var)}\s*\.\s*(query|get|next|getRowCount)\s*\(", code):
            add_unique(a.tables_read, table)
    for table in GLIDE_INLINE.findall(code):
        if table not in a.tables_read and table not in a.tables_written:
            add_unique(a.tables_read, table)

    for name in GLIDE_AJAX.findall(code):
        add_unique(a.references, name.split(".")[-1])
    for name in NEW_CLASS.findall(code) + STATIC_CALL.findall(code):
        short = name.split(".")[-1]
        if short not in NOT_DEPENDENCIES and not short.startswith("Glide") and not name.startswith("sn_"):
            add_unique(a.references, short)
    for flow in FLOW_API.findall(code):
        add_unique(a.references, flow.split(".")[-1])
        add_unique(a.behaviours, f"Starts Flow Designer flow/subflow/action '{flow}'")

    for ev in EVENT.findall(code):
        add_unique(a.events_fired, ev)
    for prop in PROPERTY.findall(code):
        add_unique(a.properties_used, prop)
    for kind, name in REST.findall(code):
        add_unique(a.integrations, f"{kind}: {name}" if name else kind)
    for fn in FUNC_DECL.findall(code) + FUNC_PROP.findall(code):
        if fn not in BOILERPLATE_FUNCTIONS:
            add_unique(a.functions, fn)
    for f1, f2 in FIELD_SET.findall(code):
        add_unique(a.fields_set, f1 or f2)
    for field in CLIENT_FIELD_SET.findall(code):
        add_unique(a.fields_set, field)

    _behaviours(code, a)
    _findings(artifact, code, client_side, a)
    return a


def _behaviours(code: str, a: Analysis) -> None:
    checks = [
        (r"setAbortAction\s*\(\s*true", "Can abort the database operation (setAbortAction)"),
        (r"setWorkflow\s*\(\s*false", "Suppresses business rules/engines on its updates (setWorkflow(false))"),
        (r"autoSysFields\s*\(\s*false", "Skips system field updates (autoSysFields(false))"),
        (r"gs\.addErrorMessage", "Shows an error message to the user"),
        (r"gs\.addInfoMessage", "Shows an info message to the user"),
        (r"g_form\.addErrorMessage|g_form\.showFieldMsg", "Shows messages on the form"),
        (r"g_form\.setMandatory", "Changes field mandatory state on the form"),
        (r"g_form\.setVisible|g_form\.setDisplay", "Shows/hides fields on the form"),
        (r"g_form\.setReadOnly|g_form\.setDisabled", "Makes fields read-only on the form"),
        (r"return\s+false\s*;", "Can stop the user action (returns false)"),
        (r"action\.setRedirectURL", "Redirects the user after running"),
        (r"gs\.hasRole|g_user\.hasRole", "Behaves differently depending on the user's roles"),
        (r"getXMLAnswer|getXML\s*\(", "Calls the server asynchronously (GlideAjax)"),
        (r"\.getXMLWait\s*\(", "Calls the server synchronously (getXMLWait)"),
        (r"new\s+GlideSysAttachment", "Works with attachments"),
        (r"current\.variables\.", "Reads catalog variables"),
    ]
    for pattern, text in checks:
        if re.search(pattern, code):
            add_unique(a.behaviours, text)


def _findings(artifact: Artifact, code: str, client_side: bool, a: Analysis) -> None:
    add = lambda sev, msg, rule: a.findings.append(Finding(sev, msg, rule))  # noqa: E731
    when = str(artifact.trigger.get("when", "")).lower()
    if artifact.type == "business_rule" and re.search(r"\bcurrent\s*\.\s*update\s*\(", code):
        add("high", "Calls current.update() inside a business rule - this re-triggers business rules and can "
                    "cause recursion. Use a 'before' rule and set fields directly instead.", "current-update")
    if artifact.type == "business_rule" and when == "before" and a.tables_written:
        add("low", "A 'before' rule writes to other tables; consider an 'after'/'async' rule so the "
                   "related updates only happen if the save succeeds.", "before-writes-other-tables")
    if client_side and GLIDE_INLINE.search(code):
        add("high", "Uses GlideRecord in client-side code - this is a synchronous server round trip. "
                    "Use GlideAjax or g_scratchpad instead.", "client-gliderecord")
    if re.search(r"\.getXMLWait\s*\(", code):
        add("medium", "Synchronous GlideAjax (getXMLWait) blocks the browser; use getXMLAnswer.", "sync-ajax")
    if re.search(r"\beval\s*\(", code):
        add("high", "Uses eval() - a security and maintainability risk.", "eval")
    if SYS_ID.search(code):
        add("medium", "Contains hard-coded sys_id values - these differ between instances. "
                      "Use a system property or look the record up by a stable key.", "hardcoded-sys-id")
    if re.search(r"\bgs\.(log|print)\s*\(|console\.log\s*\(", code):
        add("low", "Leftover debug logging (gs.log/gs.print/console.log).", "debug-logging")
    if re.search(r"while\s*\(\s*\w+\s*\.\s*next\s*\(\s*\)\s*\)\s*\{[^}]*new\s+GlideRecord", code, re.S):
        add("medium", "Queries a table inside a loop over another query (N+1 queries). Consider a single "
                      "encoded query or GlideAggregate.", "query-in-loop")
    if re.search(r"\.query\s*\(\s*\)", code) and not re.search(r"addQuery|addEncodedQuery|addActiveQuery|addNullQuery|addNotNullQuery|\.get\s*\(", code):
        add("medium", "Runs a query with no filter - it will read the whole table.", "unfiltered-query")
    if "deleteMultiple" in code:
        add("medium", "Performs bulk deletes (deleteMultiple) - double-check the filter.", "bulk-delete")
    if re.search(r"setWorkflow\s*\(\s*false", code):
        add("info", "setWorkflow(false) skips business rules, notifications and audit on the updated records.",
            "set-workflow-false")
    if artifact.type == "scheduled_job" and not a.tables_written and not a.events_fired and not a.references:
        add("info", "Scheduled job does not appear to change data or call other components.", "noop-job")
    if a.complexity > 15:
        add("medium", f"High complexity (approx. {a.complexity} decision points) - consider splitting into a "
                      "Script Include with smaller functions.", "complexity")
    if artifact.active is False:
        add("info", "Artifact is inactive.", "inactive")
    if not artifact.description and artifact.type not in ("dictionary", "system_property", "table"):
        add("low", "No description recorded on the record.", "missing-description")

