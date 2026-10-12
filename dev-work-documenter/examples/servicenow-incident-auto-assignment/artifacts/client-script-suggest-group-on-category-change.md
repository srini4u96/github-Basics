# Suggest group on category change

[← Back to overview](../README.md)

| | |
|---|---|
| Type | Client Script |
| Platform | servicenow |
| Applies to | `incident` |
| Application | global |
| Status | active |
| Created by | jane.dev |
| Last updated | 2026-09-30 10:15:00 by jane.dev |
| Source | `samples/servicenow/incident_auto_assignment_update_set.xml` |
| Record type | `sys_script_client` |
| Trigger: type | `onChange` |
| Trigger: field | `category` |
| Trigger: ui_type | `All` |

## Walkthrough

**In short:** Browser-side script that runs when the `category` field changes on `incident`.

**Purpose (from the record):** Pre-fills the assignment group on the form as soon as the category is chosen.

### What it does
- Sets field(s) `assignment_group`
- Calls `IncidentAssignmentUtils`
- Shows messages on the form
- Calls the server asynchronously (GlideAjax)

### Developer notes (from code comments)
- Ask the server which group handles this category and pre-fill it

### Connections in this delivery
- Uses → Script Include **IncidentAssignmentUtils** (calls)

_Size: 17 lines, complexity ≈ 4._

## Script

```javascript
function onChange(control, oldValue, newValue, isLoading, isTemplate) {
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
}
```
