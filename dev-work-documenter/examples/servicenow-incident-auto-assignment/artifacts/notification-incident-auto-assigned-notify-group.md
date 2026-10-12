# Incident auto-assigned - notify group

[← Back to overview](../README.md)

| | |
|---|---|
| Type | Notification |
| Platform | servicenow |
| Applies to | `incident` |
| Application | global |
| Status | active |
| Created by | jane.dev |
| Last updated | 2026-09-30 10:15:00 by jane.dev |
| Source | `samples/servicenow/incident_auto_assignment_update_set.xml` |
| Subject | ${number} has been assigned to your group |
| Recipient groups | event.parm1 |
| Record type | `sysevent_email_action` |
| Trigger: event | `x_acme.incident.auto_assigned` |

## Walkthrough

**In short:** Sends an email notification when the `x_acme.incident.auto_assigned` event is fired for `incident` records.

**Purpose (from the record):** Tells the group manager when an incident was routed to them automatically.

### Connections in this delivery
- Used by ← Business Rule **Auto-assign incident by category** (fires event 'x_acme.incident.auto_assigned')
