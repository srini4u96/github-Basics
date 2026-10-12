# Re-route stale default group incidents

[← Back to overview](../README.md)

| | |
|---|---|
| Type | Scheduled Script Execution |
| Platform | servicenow |
| Application | global |
| Status | active |
| Created by | jane.dev |
| Last updated | 2026-09-30 10:15:00 by jane.dev |
| Source | `samples/servicenow/incident_auto_assignment_update_set.xml` |
| Record type | `sysauto_script` |
| Trigger: run | `daily` |
| Trigger: time | `1970-01-01 02:00:00` |

## Walkthrough

**In short:** Background job that runs on a schedule (daily at 02:00:00).

**Purpose (from the record):** Nightly clean-up of incidents parked in the default group.

### What it does
- Reads `incident`
- Writes to (create/update/delete) `incident`
- Calls `IncidentAssignmentUtils`
- Suppresses business rules/engines on its updates (setWorkflow(false))

### Developer notes (from code comments)
- Nightly: re-route incidents stuck in the default group for more than 4 hours

### Connections in this delivery
- Uses → Script Include **IncidentAssignmentUtils** (calls)

### Review notes
- 🟠 **medium** — Contains hard-coded sys_id values - these differ between instances. Use a system property or look the record up by a stable key.
- ℹ️ **info** — setWorkflow(false) skips business rules, notifications and audit on the updated records.

_Size: 12 lines, complexity ≈ 3._

## Script

```javascript
// Nightly: re-route incidents stuck in the default group for more than 4 hours
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
}
```
