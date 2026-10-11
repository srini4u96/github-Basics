"""Adapter contract. Add a platform by subclassing ``Adapter`` and registering it."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Iterable, List, Type

from ..model import Artifact

_REGISTRY: Dict[str, Type["Adapter"]] = {}


def register(cls: Type["Adapter"]) -> Type["Adapter"]:
    _REGISTRY[cls.platform] = cls
    return cls


def get_adapter(platform: str, **options) -> "Adapter":
    try:
        return _REGISTRY[platform](**options)
    except KeyError:
        raise ValueError(
            f"Unknown platform '{platform}'. Available: {', '.join(sorted(_REGISTRY))}"
        ) from None


def available_platforms() -> List[str]:
    return sorted(_REGISTRY)


class Adapter(ABC):
    """Turns a platform's native export into platform-neutral ``Artifact`` objects."""

    platform: str = ""
    label: str = ""
    file_patterns: tuple = ("*",)

    def __init__(self, **options):
        self.options = options

    def load(self, paths: Iterable[Path]) -> List[Artifact]:
        artifacts: List[Artifact] = []
        for path in paths:
            path = Path(path)
            files = sorted(
                f for pattern in self.file_patterns for f in path.rglob(pattern) if f.is_file()
            ) if path.is_dir() else [path]
            for f in files:
                artifacts.extend(self.load_file(f))
        return self.deduplicate(artifacts)

    @abstractmethod
    def load_file(self, path: Path) -> List[Artifact]:
        ...

    def metadata(self) -> Dict[str, str]:
        """Information about the delivery itself (update set name, release...)."""
        return {}

    @staticmethod
    def deduplicate(artifacts: List[Artifact]) -> List[Artifact]:
        """Keep the most recently updated version when a record appears more than once."""
        latest: Dict[str, Artifact] = {}
        for artifact in artifacts:
            current = latest.get(artifact.key)
            if current is None or (artifact.updated_on or "") >= (current.updated_on or ""):
                latest[artifact.key] = artifact
        return list(latest.values())
