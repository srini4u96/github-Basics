from __future__ import annotations

from abc import ABC, abstractmethod

from ..model import Artifact, DocumentationSet


class Explainer(ABC):
    """Writes the human walkthrough (Markdown) for artifacts and for the whole delivery."""

    @abstractmethod
    def explain_artifact(self, artifact: Artifact, docset: DocumentationSet) -> str:
        ...

    @abstractmethod
    def overview(self, docset: DocumentationSet) -> str:
        ...

    def run(self, docset: DocumentationSet) -> DocumentationSet:
        for artifact in docset.artifacts:
            artifact.explanation = self.explain_artifact(artifact, docset)
        docset.overview = self.overview(docset)
        return docset
