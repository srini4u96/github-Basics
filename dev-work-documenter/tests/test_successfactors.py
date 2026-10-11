import json

from conftest import SAMPLES

from devdoc.adapters import get_adapter
from devdoc.analyzers import analyze
from devdoc.model import DocumentationSet


def test_odata_rules_and_csv_integrations():
    arts = {a.name: a for a in get_adapter("successfactors").load([SAMPLES / "successfactors"])}
    rule = arts["Default probation end date"]
    assert rule.type == "business_rule" and rule.target == "Job Information" and rule.active is True
    assert rule.trigger == {"scenario": "Basic", "event": "onSave", "base_object": "Job Information"}
    assert len(rule.steps) == 2
    integ = arts["Daily badge system export"]
    assert integ.type == "integration" and len(integ.steps) == 4
    assert integ.steps[3].detail == "Lookup site code"


def test_rule_analysis_and_dependencies():
    arts = get_adapter("successfactors").load([SAMPLES / "successfactors"])
    docset = analyze(DocumentationSet("t", "successfactors", arts))
    by_name = {a.name: a for a in arts}
    probation = by_name["Default probation end date"].analysis
    assert probation.fields_set == ["Job Information.Probation Period End Date"]
    assert probation.tables_written == ["Job Information"]
    salary = by_name["Validate salary within pay range"].analysis
    assert set(salary.tables_read) == {"Compensation Information", "Pay Range"}
    assert "COMP_EXCEPTION_APPROVAL" in salary.references
    keys = docset.by_key()
    assert {(keys[d.source].name, keys[d.target].name) for d in docset.dependencies} == {
        ("Create badge request on hire", "Default probation end date")}


def test_custom_column_mapping(tmp_path):
    (tmp_path / "rules.csv").write_text("Regel,Bezeichnung,Objekt\nR1,My rule,Position\n")
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"id": "Regel", "name": "Bezeichnung", "base_object": "Objekt"}))
    [art] = get_adapter("successfactors", mapping=str(mapping)).load([tmp_path / "rules.csv"])
    assert (art.id, art.name, art.target, art.type) == ("R1", "My rule", "Position", "business_rule")
