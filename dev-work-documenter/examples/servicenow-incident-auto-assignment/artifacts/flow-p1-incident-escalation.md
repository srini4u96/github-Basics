# P1 incident escalation

[← Back to overview](../README.md)

| | |
|---|---|
| Type | Flow Designer |
| Platform | servicenow |
| Applies to | `incident` |
| Application | global |
| Status | active |
| Created by | jane.dev |
| Last updated | 2026-09-30 10:15:00 by jane.dev |
| Source | `samples/servicenow/incident_auto_assignment_update_set.xml` |
| Flow type | flow |
| Run as | system |
| Flow status | published |
| Internal name | p1_incident_escalation |
| Record type | `sys_hub_flow` |
| Trigger: type | `Created or Updated` |
| Trigger: table | `incident` |
| Trigger: condition | `priority=1^active=true` |

## Walkthrough

**In short:** Flow Designer flow triggered by **Created or Updated** on `incident` when `priority=1^active=true`, with 3 step(s).

**Purpose (from the record):** Pages the on-call manager and opens a major incident bridge for P1 incidents.

### Step by step
1. **Look Up Record** — Find the on-call manager for the assignment group _(action)_
2. **Send Notification** — Page the on-call manager _(action)_
3. **Update Record** — Set major incident state to 'Proposed' _(action)_
