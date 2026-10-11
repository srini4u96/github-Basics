from .base import Explainer
from .template import TemplateExplainer


def get_explainer(name: str = "template", **options) -> Explainer:
    if name == "template":
        return TemplateExplainer()
    if name == "claude":
        from .claude import ClaudeExplainer  # optional dependency
        return ClaudeExplainer(**options)
    raise ValueError(f"Unknown explainer '{name}' (use 'template' or 'claude')")


__all__ = ["Explainer", "TemplateExplainer", "get_explainer"]
