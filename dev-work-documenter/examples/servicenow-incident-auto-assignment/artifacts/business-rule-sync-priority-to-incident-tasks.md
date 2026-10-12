# Sync priority to incident tasks

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
| Trigger: when | `after` |
| Trigger: operations | update |
| Trigger: order | `200` |
| Trigger: filter_condition | `priorityVALCHANGES^EQ` |

## Walkthrough

**In short:** Server-side rule that runs **after** a record is **updated** on `incident` (filter: `priorityVALCHANGES^EQ`).

### What it does
- Reads `incident_task`
- Writes to (create/update/delete) `incident_task`
- Sets field(s) `u_last_priority_sync`

### Developer notes (from code comments)
- Copy the priority to all child tasks so SLAs stay aligned

### Review notes
- 🔴 **high** — Calls current.update() inside a business rule - this re-triggers business rules and can cause recursion. Use a 'before' rule and set fields directly instead.
- 🟡 **low** — Leftover debug logging (gs.log/gs.print/console.log).
- 🟡 **low** — No description recorded on the record.

_Size: 12 lines, complexity ≈ 2._

## Script

```javascript
(function executeRule(current, previous) {
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
})(current, previous);
```
