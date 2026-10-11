from conftest import SAMPLES

from devdoc.adapters import get_adapter
from devdoc.analyzers import analyze
from devdoc.model import Artifact, DocumentationSet
from devdoc.analyzers.servicenow_js import analyze as analyze_js

UPDATE_SET = SAMPLES / "servicenow" / "incident_auto_assignment_update_set.xml"


def load():
    adapter = get_adapter("servicenow")
    artifacts = adapter.load([UPDATE_SET])
    return adapter, {a.name: a for a in artifacts}


def test_update_set_is_parsed_into_artifacts():
    adapter, arts = load()
    assert adapter.metadata()["update_set"] == "STRY0012345 - Incident auto-assignment"
    br = arts["Auto-assign incident by category"]
    assert br.type == "business_rule" and br.target == "incident"
    assert br.trigger["when"] == "before" and br.trigger["operations"] == ["insert"]
    assert "IncidentAssignmentUtils" in br.scripts["Script"]
    assert arts["IncidentAssignmentUtils"].properties["Client callable"] == "true"


def test_flow_children_are_attached_as_ordered_steps():
    _, arts = load()
    flow = arts["P1 incident escalation"]
    assert flow.trigger["table"] == "incident"
    assert [s.label for s in flow.steps] == ["Look Up Record", "Send Notification", "Update Record"]


def test_dependencies_between_components():
    _, arts = load()
    docset = analyze(DocumentationSet("t", "servicenow", list(arts.values())))
    keys = docset.by_key()
    edges = {(keys[d.source].name, keys[d.target].name, d.reason) for d in docset.dependencies}
    assert ("Auto-assign incident by category", "IncidentAssignmentUtils", "calls") in edges
    assert ("Suggest group on category change", "IncidentAssignmentUtils", "calls") in edges
    assert ("Auto-assign incident by category", "Incident auto-assigned - notify group",
            "fires event 'x_acme.incident.auto_assigned'") in edges
    assert ("IncidentAssignmentUtils", "x_acme.incident.default_group", "reads property") in edges


def _art(code, type_="business_rule", **kw):
    return Artifact(platform="servicenow", type=type_, type_label=type_, name="x", id="x",
                    scripts={"Script": code}, description="d", **kw)


def test_js_analysis_extracts_tables_and_writes():
    a = analyze_js(_art("""
        var gr = new GlideRecord('incident'); gr.addQuery('active', true); gr.query();
        while (gr.next()) { gr.state = 2; gr.update(); }
        var log = new GlideRecord('u_log'); log.initialize(); log.insert();
        gs.eventQueue('my.event', current);
    """))
    assert a.tables_read == ["incident"]
    assert set(a.tables_written) == {"incident", "u_log"}
    assert a.events_fired == ["my.event"]


def test_js_findings():
    rules = lambda code, **kw: {f.rule for f in analyze_js(_art(code, **kw)).findings}  # noqa: E731
    assert "current-update" in rules("current.update();")
    assert "hardcoded-sys-id" in rules("var id = '46d44a5dc0a8010e0118ec7a2bdee8f3';")
    assert "client-gliderecord" in rules("var g = new GlideRecord('incident');", type_="client_script")
    assert "eval" in rules("eval(x);")
    assert "unfiltered-query" in rules("var g = new GlideRecord('incident'); g.query();")
    # comments must not trigger findings
    assert "current-update" not in rules("// current.update();")


def test_glide_classes_are_not_dependencies():
    a = analyze_js(_art("var d = new GlideDateTime(); var u = new MyUtil(); JSON.stringify(Math.max(1,2));"))
    assert a.references == ["MyUtil"]


def test_record_xml_and_deleted_records(tmp_path):
    f = tmp_path / "sys_script_include_1.xml"
    f.write_text('<?xml version="1.0"?><record_update table="sys_script_include">'
                 '<sys_script_include action="DELETE"><sys_id>1</sys_id><name>OldUtil</name>'
                 '<script>var OldUtil = Class.create();</script></sys_script_include></record_update>')
    arts = get_adapter("servicenow").load([tmp_path])
    assert len(arts) == 1 and arts[0].deleted and arts[0].name == "OldUtil"
