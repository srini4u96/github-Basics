"""Platform adapters. Importing this package registers all built-in adapters."""
from .base import Adapter, available_platforms, get_adapter, register
from . import generic, servicenow, successfactors  # noqa: F401  (registration side effect)

__all__ = ["Adapter", "available_platforms", "get_adapter", "register"]
