from __future__ import annotations

from typing import Any

from .erpnext import ERPNextAdapter
from .generic import GenericRESTAdapter
from .mock import MockAdapter


def build_adapter(adapter_name: str | None = None, **kwargs: Any) -> Any:
    name = (adapter_name or __import__("os").getenv("ADAPTER", "mock")).lower()
    if name == "erpnext":
        return ERPNextAdapter(**kwargs)
    if name == "generic":
        return GenericRESTAdapter(**kwargs)
    return MockAdapter(**kwargs)
