import json
from types import SimpleNamespace

import pytest

from conftest import SAMPLES

from devdoc import build_documentation
from devdoc.cli import main
from devdoc.render.html import md_to_html


def test_cli_generates_all_formats(tmp_path, capsys):
    code = main(["generate", "-p", "servicenow", "-i", str(SAMPLES / "servicenow"), "-o", str(tmp_path),
                 "-f", "md,html,json"])
    assert code == 0
    index = (tmp_path / "README.md").read_text()
    assert "## Component map" in index and "IncidentAssignmentUtils" in index
    assert len(list((tmp_path / "artifacts").glob("*.md"))) == 10
    html = (tmp_path / "documentation.html").read_text()
    assert html.startswith("<!doctype html>") and "Sync priority to incident tasks" in html
    data = json.loads((tmp_path / "documentation.json").read_text())
    assert len(data["artifacts"]) == 10


def test_fail_on_high_exit_code(tmp_path):
    args = ["generate", "-p", "servicenow", "-i", str(SAMPLES / "servicenow"), "-o", str(tmp_path), "-f", "json"]
    assert main(args + ["--fail-on-high"]) == 2


def test_type_filter_and_generic_platform(tmp_path):
    docset = build_documentation("servicenow", [SAMPLES / "servicenow"], include_types=["business_rule"])
    assert {a.type for a in docset.artifacts} == {"business_rule"}
    generic = build_documentation("generic", [SAMPLES / "generic"], out_dir=tmp_path, formats=["md"])
    assert generic.artifacts[0].platform == "salesforce"
    assert "PipelineService" in (tmp_path / "artifacts" / "apex-trigger-opportunitytrigger.md").read_text()


def test_markdown_to_html_escapes_and_formats():
    out = md_to_html("### Title\n- **bold** `<script>`\n\n```\na < b\n```")
    assert "<h4>Title</h4>" in out and "<strong>bold</strong>" in out
    assert "&lt;script&gt;" in out and "<script>" not in out and "a &lt; b" in out


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", content=[
            SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="### Summary\nAI text")])


def test_claude_explainer_with_fake_client(tmp_path):
    pytest.importorskip("anthropic")
    fake = FakeMessages()
    client = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    docset = build_documentation("servicenow", [SAMPLES / "servicenow"], explainer="claude",
                                 include_types=["script_include"], explainer_options={"client": client})
    assert docset.artifacts[0].explanation == "### Summary\nAI text"
    assert docset.overview == "### Summary\nAI text"
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["thinking"] == {"type": "adaptive"}
    assert "getGroupForCategory" in call["messages"][0]["content"]


def test_claude_refusal_falls_back_to_offline_text():
    pytest.importorskip("anthropic")
    class Refusing(FakeMessages):
        def create(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", content=[])
    client = SimpleNamespace(beta=SimpleNamespace(messages=Refusing()))
    docset = build_documentation("servicenow", [SAMPLES / "servicenow"], explainer="claude",
                                 include_types=["script_include"], explainer_options={"client": client})
    assert "**In short:**" in docset.artifacts[0].explanation
    assert "AI explanation unavailable" in docset.artifacts[0].explanation
