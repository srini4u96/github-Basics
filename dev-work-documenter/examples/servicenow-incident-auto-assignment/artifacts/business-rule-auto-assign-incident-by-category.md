# Auto-assign incident by category

[← Back to overview](../README.md)

| | |
|---|---|
| Type | Business Rule |
| Platform | servicenow |
| Applies to | `incident` |
| Application | global |
| Status | active |
| Created by | jane.dev |
| Last updated | 2026-09-30 10:15:00 by jane.dev |
| Source | `samples/servicenow/incident_auto_assignment_update_set.xml` |
| Advanced | true |
| Record type | `sys_script` |
| Trigger: when | `before` |
| Trigger: operations | insert |
| Trigger: order | `100` |
| Trigger: condition | `current.category.changes() \|\| current.assignment_group.nil()` |

## Walkthrough

**In short:** Server-side rule that runs **before** a record is **inserted** on `incident`, only when `current.category.changes() || current.assignment_group.nil()`.

**Purpose (from the record):** Sets the assignment group on new incidents using the category matrix.

### What it does
- Sets field(s) `assignment_group` and `work_notes`
- Calls `IncidentAssignmentUtils`
- Fires event(s) `x_acme.incident.auto_assigned`
- Can abort the database operation (setAbortAction)
- Shows an error message to the user

### Developer notes (from code comments)
- null when async
- Only auto-assign when the caller did not pick a group

### Connections in this delivery
- Uses → Script Include **IncidentAssignmentUtils** (calls)
- Uses → Notification **Incident auto-assigned - notify group** (fires event 'x_acme.incident.auto_assigned')

_Size: 14 lines, complexity ≈ 3._

## Script

```javascript
(function executeRule(current, previous /*null when async*/) {
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
})(current, previous);
```
