# devdoc — Development Work Documenter

**The problem:** one developer builds Business Rules, Script Includes, Flows, Client Scripts (or SuccessFactors
Business Rules, MDF objects, integrations…), and everyone else in the team depends on that person for a
walkthrough before they can support, test, or extend it.

**The solution:** `devdoc` reads what the developer already produces (an update set export, a
configuration export) and generates a **handover document** that explains the work:

- **What each component does, and when it runs.** For example, "runs *before* an incident is *inserted*, only when…".
- **A step-by-step walkthrough**: flow steps, rule conditions, functions, and the developer's own code comments.
- **The data it touches**: tables or objects read and written, fields set, events fired, properties, and external calls.
- **How the pieces connect**: Business Rule → Script Include → System Property, event → Notification, with a component map.
- **Where to start reading**: the entry points that users, data changes or schedules trigger.
- **Review notes**: platform best-practice risks, such as `current.update()` in a Business Rule, client-side GlideRecord, hard-coded sys_ids, or N+1 queries.
- **Optional AI walkthroughs (Claude)**: narrative, line-by-line explanations plus test steps, the way the original developer would explain them.

The design is **platform-neutral**. ServiceNow and SuccessFactors are adapters on top of a common
model, so you can add another platform without touching the analysis or output code.

```
 ServiceNow update set ─┐                ┌─ analyzers ──┐                ┌─ README.md + one page per component
 SuccessFactors export ─┼─► adapters ─► common model ──►│ facts, risks, ├─► explainers ─► renderers ─┼─ documentation.html (single file)
 Any platform (JSON)  ──┘                │ dependencies  │ (offline/AI)    └─ documentation.json (for publishing)
```

## Quick start

```bash
cd dev-work-documenter
pip install -e .            # no required dependencies; add ".[ai]" for Claude, ".[secure]" for defusedxml

# ServiceNow: document an exported update set (Retrieved/Local Update Set → Export to XML)
devdoc generate -p servicenow -i samples/servicenow/incident_auto_assignment_update_set.xml -o docs-out

# SuccessFactors: rules / integrations exported as JSON (OData) or CSV
devdoc generate -p successfactors -i samples/successfactors -o docs-out-sf
```

Open `docs-out/documentation.html`, or browse `docs-out/README.md`. A pre-generated example is in
[`examples/servicenow-incident-auto-assignment`](examples/servicenow-incident-auto-assignment/README.md).

You can also run it without installing it: `python -m devdoc generate ...`.

### Pull an update set straight from an instance

```bash
export SN_USER=docs.reader SN_PASSWORD=...      # read-only account with access to sys_update_set / sys_update_xml
devdoc pull-servicenow --instance acme.service-now.com --update-set "STRY0012345 - Incident auto-assignment" -o us.xml
devdoc generate -p servicenow -i us.xml -o docs-out
```

### AI walkthroughs with Claude (optional)

```bash
pip install -e ".[ai]"
export ANTHROPIC_API_KEY=...     # or: ant auth login
devdoc generate -p servicenow -i us.xml -o docs-out --explainer claude [--effort high]
```

The static-analysis facts are sent with the code, so explanations stay grounded. Each component gets a
Summary, When it runs, Walkthrough, Data and side effects, Dependencies, Things to watch, and How to test
section, and you get an end-to-end overview of the whole delivery. If a call fails, the tool falls back to
the offline explanation for that component.
> ⚠️ `--explainer claude` sends component source code to the Anthropic API. Check your data policies first.
> The default `template` explainer runs fully offline.

## Supported inputs

| Platform | Input | Components understood |
|---|---|---|
| `servicenow` | Update set XML export, single record XML exports, or the `update/*.xml` folder of a source-controlled app (folders are scanned recursively) | Business Rule, Script Include, Client Script, Catalog Client Script, UI Action, UI Policy, Scheduled Job, Script Action, Notification, Scripted REST resource, Fix Script, ACL, Flow Designer flow (trigger + ordered actions), Flow action, Table, Dictionary field, System Property. Other tables are handled generically: every field containing "script" is documented. |
| `successfactors` | JSON (list, OData v2 `{"d":{"results":[...]}}`, or `{"artifacts":[...]}`) or CSV | Business Rule (IF/THEN conditions, fields set, rules and workflows called), Integration Center integration (source, destination, schedule, field mappings), MDF object, Workflow, Picklist, Permission Role |
| `generic` | JSON in the neutral model shape ([example](samples/generic/salesforce_example.json)) | Anything: Salesforce, Workday, SAP BTP, in-house apps… |

**SuccessFactors column names** vary by tenant and by export tool. Common names are recognised
automatically (`ruleId`, `externalCode`, `baseObject`, `ruleScenario`…). For anything else, pass a
mapping file:

```json
{"id": "Rule ID", "name": "Rule Name", "base_object": "Base Object", "conditions": "Rule Definition"}
```
```bash
devdoc generate -p successfactors -i export.csv --mapping mapping.json --sf-type business_rule
```

## Useful options

| Option | Purpose |
|---|---|
| `-f md,html,json` | Choose the output formats. Use Markdown for Git, wikis and Confluence imports, HTML to email or attach to a story, and JSON to publish anywhere. |
| `--types business_rule,script_include` | Document only some component types |
| `-t "Sprint 14 handover"` | Set the document title |
| `--fail-on-high` | Exit with code 2 when a high-severity review note exists (for CI and peer-review gates) |

## Suggested team workflow

1. When a story is complete, the developer exports the update set (or CI pulls it with `pull-servicenow`).
2. `devdoc generate …` runs and the output is attached to the story or change, or committed to a `docs/` repo or wiki.
3. Reviewers and support staff read the walkthrough instead of booking a session. The *Review notes* section
   doubles as a code-review checklist.

Example GitHub Actions step:

```yaml
- run: pip install ./dev-work-documenter
- run: devdoc generate -p servicenow -i exports/ -o handover --fail-on-high
- uses: actions/upload-artifact@v4
  with: { name: handover-docs, path: handover }
```

## Extending to another platform

1. Create `devdoc/adapters/<platform>.py`. Subclass `Adapter`, set `platform` and `file_patterns`, and
   implement `load_file(path) -> list[Artifact]` to map the native export into `Artifact` objects (name, type,
   target, trigger, scripts, steps, properties).
2. Import the module in `devdoc/adapters/__init__.py`.
3. Optional: register a code analyzer for the platform's language in `devdoc/analyzers/__init__.py`
   (`ANALYZERS[(platform, language)] = fn`). Declarative steps (`language="rule"`) already use the rules analyzer.

Explanations, dependency mapping, and all output formats then work unchanged. To support a new ServiceNow
record type, add one entry to `TABLE_SPECS` in `devdoc/adapters/servicenow.py`.

## Project layout

```
devdoc/
  model.py              platform-neutral Artifact / DocumentationSet model
  adapters/             servicenow.py, successfactors.py, generic.py (+ base registry)
  analyzers/            servicenow_js.py (Glide APIs, risks), rules.py (declarative rules), dependency graph
  explain/              template.py (offline), claude.py (AI walkthroughs)
  render/               markdown.py, html.py, json_out.py
  cli.py, pipeline.py
samples/                example ServiceNow update set, SuccessFactors exports, generic JSON
examples/               generated documentation for the ServiceNow sample
tests/                  pytest suite: pip install -e ".[dev]" && python -m pytest tests
```

## Known limitations

- Code analysis uses patterns, not a full JavaScript parser. It is tuned to surface what a reviewer looks
  for, and it can miss dynamically built table names (`new GlideRecord(tableVar)`).
- Flow Designer: the trigger and the ordered actions, subflows and logic are documented from their
  `sys_hub_*` records. Inputs stored in compressed `_v2` values are not decoded, so use `--explainer claude`
  or the flow description for detail.
- The HTML component map loads Mermaid from a CDN. If you are offline, the diagram source shows instead,
  and the same connections are always listed in text.
