# IncidentAssignmentUtils

[← Back to overview](../README.md)

| | |
|---|---|
| Type | Script Include |
| Platform | servicenow |
| Application | global |
| Status | active |
| Created by | jane.dev |
| Last updated | 2026-09-30 10:15:00 by jane.dev |
| Source | `samples/servicenow/incident_auto_assignment_update_set.xml` |
| API name | global.IncidentAssignmentUtils |
| Client callable | true |
| Accessible from | package_private |
| Record type | `sys_script_include` |
| Trigger: invoked | `called from other server scripts and from the browser via GlideAjax` |

## Walkthrough

**In short:** Reusable server-side library, called from other server scripts and from the browser via GlideAjax, exposing `getGroupForCategory` and `ajaxGetGroup`.

**Purpose (from the record):** Looks up the right support group for an incident from the assignment matrix.

### What it does
- Reads `u_assignment_matrix` and `sys_user_group`
- Reads configuration `x_acme.incident.default_group`

### Functions
- `getGroupForCategory()`
- `ajaxGetGroup()`

### Developer notes (from code comments)
- Finds the support group for a category using the u_assignment_matrix table.
- Fall back to the default service desk group configured in a property
- Called from the client script via GlideAjax

### Connections in this delivery
- Uses → System Property **x_acme.incident.default_group** (reads property)
- Uses → Table **Assignment Matrix** (reads table)
- Used by ← Business Rule **Auto-assign incident by category** (calls)
- Used by ← Client Script **Suggest group on category change** (calls)
- Used by ← Scheduled Script Execution **Re-route stale default group incidents** (calls)

_Size: 27 lines, complexity ≈ 3._

## Script

```javascript
var IncidentAssignmentUtils = Class.create();
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
});
```
