"""Regenerates incident_auto_assignment_update_set.xml - a realistic update set export.

Run: python samples/servicenow/build_sample.py
"""
import xml.etree.ElementTree as ET
from pathlib import Path

DEV, WHEN, SCOPE = "jane.dev", "2026-09-30 10:15:00", "global"

SCRIPT_INCLUDE = """var IncidentAssignmentUtils = Class.create();
IncidentAssignmentUtils.prototype = Object.extendsObject(AbstractAjaxProcessor, {

    // Finds the support group for a category using the u_assignment_matrix table.
    getGroupForCategory: function(category, location) {
        var matrix = new GlideRecord('u_assignment_matrix');
        matrix.addQuery('u_category', category);
        matrix.addQuery('u_location', location);
        matrix.addActiveQuery();
        matrix.orderBy('u_priority');
        matrix.setLimit(1);
        matrix.query();
        if (matrix.next()) {
            return matrix.getValue('u_group');
        }
        // Fall back to the default service desk group configured in a property
        return gs.getProperty('x_acme.incident.default_group');
    },

    /* Called from the client script via GlideAjax */
    ajaxGetGroup: function() {
        var category = this.getParameter('sysparm_category');
        var location = this.getParameter('sysparm_location');
        var groupId = this.getGroupForCategory(category, location);
        var group = new GlideRecord('sys_user_group');
        if (group.get(groupId)) {
            return JSON.stringify({ sys_id: groupId, name: group.getDisplayValue() });
        }
        return '';
    },

    type: 'IncidentAssignmentUtils'
});"""

BR_ASSIGN = """(function executeRule(current, previous /*null when async*/) {
    // Only auto-assign when the caller did not pick a group
    if (!current.assignment_group.nil())
        return;

    var utils = new IncidentAssignmentUtils();
    var groupId = utils.getGroupForCategory(current.getValue('category'), current.getValue('location'));
    if (groupId) {
        current.assignment_group = groupId;
        current.work_notes = 'Auto-assigned by category matrix';
        gs.eventQueue('x_acme.incident.auto_assigned', current, groupId, current.getValue('category'));
    } else {
        gs.addErrorMessage('No assignment group found for this category. Please choose one.');
        current.setAbortAction(true);
    }
})(current, previous);"""

BR_SYNC = """(function executeRule(current, previous) {
    // Copy the priority to all child tasks so SLAs stay aligned
    var task = new GlideRecord('incident_task');
    task.addQuery('incident', current.sys_id);
    task.query();
    while (task.next()) {
        task.priority = current.priority;
        task.update();
    }
    current.u_last_priority_sync = new GlideDateTime();
    current.update();
    gs.log('Priority synced for ' + current.number);
})(current, previous);"""

CLIENT = """function onChange(control, oldValue, newValue, isLoading, isTemplate) {
    if (isLoading || newValue === '') {
        return;
    }
    // Ask the server which group handles this category and pre-fill it
    var ga = new GlideAjax('IncidentAssignmentUtils');
    ga.addParam('sysparm_name', 'ajaxGetGroup');
    ga.addParam('sysparm_category', newValue);
    ga.addParam('sysparm_location', g_form.getValue('location'));
    ga.getXMLAnswer(function(answer) {
        if (!answer) {
            g_form.showFieldMsg('category', 'No default group for this category', 'info');
            return;
        }
        var group = JSON.parse(answer);
        g_form.setValue('assignment_group', group.sys_id, group.name);
    });
}"""

JOB = """// Nightly: re-route incidents stuck in the default group for more than 4 hours
var gr = new GlideRecord('incident');
gr.addEncodedQuery('active=true^assignment_group=d625dccec0a8016700a222a0f7900d06^sys_updated_onRELATIVELT@hour@ago@4');
gr.query();
var utils = new IncidentAssignmentUtils();
while (gr.next()) {
    var groupId = utils.getGroupForCategory(gr.getValue('category'), gr.getValue('location'));
    if (groupId) {
        gr.assignment_group = groupId;
        gr.setWorkflow(false);
        gr.update();
    }
}"""


def record(table, sys_id, fields):
    root = ET.Element("record_update", table=table)
    rec = ET.SubElement(root, table, action="INSERT_OR_UPDATE")
    base = {"sys_id": sys_id, "sys_scope": SCOPE, "sys_created_by": DEV, "sys_updated_by": DEV, "sys_updated_on": WHEN}
    for key, value in {**base, **fields}.items():
        if isinstance(value, tuple):  # reference: (sys_id, display value)
            ET.SubElement(rec, key, display_value=value[1]).text = value[0]
        else:
            ET.SubElement(rec, key).text = value
    return '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="unicode")


FLOW_ID = "f1a0000000000000000000000000f10w"
RECORDS = [
    ("sys_script_include", "a1000000000000000000000000000001", {
        "name": "IncidentAssignmentUtils", "api_name": "global.IncidentAssignmentUtils", "client_callable": "true",
        "access": "package_private", "active": "true", "script": SCRIPT_INCLUDE,
        "description": "Looks up the right support group for an incident from the assignment matrix."}),
    ("sys_script", "b1000000000000000000000000000001", {
        "name": "Auto-assign incident by category", "collection": "incident", "when": "before", "order": "100",
        "action_insert": "true", "action_update": "false", "advanced": "true", "active": "true",
        "condition": "current.category.changes() || current.assignment_group.nil()",
        "script": BR_ASSIGN, "description": "Sets the assignment group on new incidents using the category matrix."}),
    ("sys_script", "b1000000000000000000000000000002", {
        "name": "Sync priority to incident tasks", "collection": "incident", "when": "after", "order": "200",
        "action_insert": "false", "action_update": "true", "advanced": "true", "active": "true",
        "filter_condition": "priorityVALCHANGES^EQ", "script": BR_SYNC, "description": ""}),
    ("sys_script_client", "c1000000000000000000000000000001", {
        "name": "Suggest group on category change", "table": "incident", "type": "onChange", "field_name": "category",
        "ui_type": "10", "active": "true", "script": CLIENT,
        "description": "Pre-fills the assignment group on the form as soon as the category is chosen."}),
    ("sysauto_script", "d1000000000000000000000000000001", {
        "name": "Re-route stale default group incidents", "run_type": "daily", "run_time": "1970-01-01 02:00:00",
        "active": "true", "script": JOB, "description": "Nightly clean-up of incidents parked in the default group."}),
    ("sysevent_email_action", "e1000000000000000000000000000001", {
        "name": "Incident auto-assigned - notify group", "collection": "incident",
        "event_name": "x_acme.incident.auto_assigned", "subject": "${number} has been assigned to your group",
        "recipient_groups": "event.parm1", "active": "true",
        "description": "Tells the group manager when an incident was routed to them automatically."}),
    ("sys_properties", "f1000000000000000000000000000001", {
        "name": "x_acme.incident.default_group", "value": "d625dccec0a8016700a222a0f7900d06", "type": "string",
        "description": "Fallback assignment group when no matrix entry matches."}),
    ("sys_db_object", "a2000000000000000000000000000001", {
        "name": "u_assignment_matrix", "label": "Assignment Matrix", "super_class": "", "access": "public"}),
    ("sys_dictionary", "a3000000000000000000000000000001", {
        "name": "u_assignment_matrix", "element": "u_group", "column_label": "Group",
        "internal_type": ("reference", "Reference"), "reference": ("sys_user_group", "sys_user_group"),
        "mandatory": "true"}),
    ("sys_hub_flow", FLOW_ID, {
        "name": "P1 incident escalation", "internal_name": "p1_incident_escalation", "type": "flow",
        "run_as": "system", "status": "published", "active": "true",
        "description": "Pages the on-call manager and opens a major incident bridge for P1 incidents."}),
    ("sys_hub_trigger_instance", "a4000000000000000000000000000001", {
        "flow": (FLOW_ID, "P1 incident escalation"), "trigger_type": "Created or Updated", "table": "incident",
        "condition": "priority=1^active=true"}),
    ("sys_hub_action_instance", "a4000000000000000000000000000002", {
        "flow": (FLOW_ID, "P1 incident escalation"), "order": "1",
        "action_type": ("x1", "Look Up Record"), "comment": "Find the on-call manager for the assignment group"}),
    ("sys_hub_action_instance", "a4000000000000000000000000000003", {
        "flow": (FLOW_ID, "P1 incident escalation"), "order": "2",
        "action_type": ("x2", "Send Notification"), "comment": "Page the on-call manager"}),
    ("sys_hub_action_instance", "a4000000000000000000000000000004", {
        "flow": (FLOW_ID, "P1 incident escalation"), "order": "3",
        "action_type": ("x3", "Update Record"), "comment": "Set major incident state to 'Proposed'"}),
]


def main():
    unload = ET.Element("unload", unload_date="2026-10-01 09:00:00")
    header = ET.SubElement(unload, "sys_remote_update_set", action="INSERT_OR_UPDATE")
    for key, value in {"name": "STRY0012345 - Incident auto-assignment", "application_name": "Global",
                       "description": "Route new incidents to the right group automatically and escalate P1s.",
                       "sys_created_by": DEV, "state": "loaded"}.items():
        ET.SubElement(header, key).text = value
    for table, sys_id, fields in RECORDS:
        row = ET.SubElement(unload, "sys_update_xml", action="INSERT_OR_UPDATE")
        ET.SubElement(row, "action").text = "INSERT_OR_UPDATE"
        ET.SubElement(row, "name").text = f"{table}_{sys_id}"
        ET.SubElement(row, "type").text = table
        ET.SubElement(row, "payload").text = record(table, sys_id, fields)
    out = Path(__file__).with_name("incident_auto_assignment_update_set.xml")
    ET.indent(unload)
    ET.ElementTree(unload).write(out, encoding="utf-8", xml_declaration=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
