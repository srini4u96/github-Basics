"""Command line interface.

    devdoc generate -p servicenow -i my_update_set.xml -o docs
    devdoc generate -p servicenow -i export.xml -o docs --explainer claude
    devdoc pull-servicenow --instance acme.service-now.com --update-set "STRY0012345" -o export.xml
    devdoc platforms
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .adapters import available_platforms, get_adapter


def _generate(args) -> int:
    from .pipeline import build_documentation

    adapter_options = {}
    if args.mapping:
        adapter_options["mapping"] = args.mapping
    if args.sf_type:
        adapter_options["sf_type"] = args.sf_type
    explainer_options = {"effort": args.effort}
    if args.model:
        explainer_options["model"] = args.model
    docset = build_documentation(
        platform=args.platform, inputs=args.input, out_dir=args.out, formats=args.format.split(","),
        explainer=args.explainer, title=args.title,
        include_types=args.types.split(",") if args.types else None,
        adapter_options=adapter_options, explainer_options=explainer_options)
    if not docset.artifacts:
        print("No artifacts found in the input.", file=sys.stderr)
        return 1
    high = sum(1 for a in docset.artifacts for f in a.analysis.findings if f.severity == "high")
    print(f"Documented {len(docset.artifacts)} component(s), {len(docset.dependencies)} connection(s), "
          f"{high} high-severity review note(s) -> {args.out}")
    return 2 if args.fail_on_high and high else 0


def _pull(args) -> int:
    from .adapters.servicenow import pull_update_set

    path = pull_update_set(args.instance, args.update_set, Path(args.out))
    print(f"Saved update set to {path}")
    return 0


def _platforms(_args) -> int:
    for name in available_platforms():
        adapter = get_adapter(name)
        print(f"{name:16} {adapter.label}  (reads {', '.join(adapter.file_patterns)})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="devdoc", description="Generate walkthrough documentation for platform development work.")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate documentation from exports")
    gen.add_argument("-p", "--platform", required=True, choices=available_platforms())
    gen.add_argument("-i", "--input", required=True, nargs="+", help="Export file(s) or folder(s)")
    gen.add_argument("-o", "--out", default="docs-out", help="Output folder (default: docs-out)")
    gen.add_argument("-f", "--format", default="md,html", help="Comma list of md,html,json (default: md,html)")
    gen.add_argument("-t", "--title", help="Document title (default: update set / platform name)")
    gen.add_argument("--types", help="Only these artifact types, e.g. business_rule,script_include")
    gen.add_argument("--explainer", default="template", choices=["template", "claude"],
                     help="template = offline; claude = AI walkthroughs (sends code to the Anthropic API)")
    gen.add_argument("--model", help="Claude model id (default: claude-opus-5-5)")
    gen.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    gen.add_argument("--mapping", help="SuccessFactors: JSON file mapping canonical fields to export columns")
    gen.add_argument("--sf-type", help="SuccessFactors: artifact type when the file has no type column")
    gen.add_argument("--fail-on-high", action="store_true", help="Exit 2 if any high-severity review note (for CI)")
    gen.set_defaults(func=_generate)

    pull = sub.add_parser("pull-servicenow", help="Download an update set from an instance (uses SN_USER/SN_PASSWORD)")
    pull.add_argument("--instance", required=True)
    pull.add_argument("--update-set", required=True, help="Update set name or sys_id")
    pull.add_argument("-o", "--out", default="update_set.xml")
    pull.set_defaults(func=_pull)

    sub.add_parser("platforms", help="List supported platforms").set_defaults(func=_platforms)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    return args.func(args)
