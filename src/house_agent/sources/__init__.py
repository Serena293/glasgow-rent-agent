from __future__ import annotations

from .generic import GenericSource


def make_source(name: str, config: dict, runtime_config: dict):
    adapter = config.get("adapter", "generic")
    if adapter != "generic":
        raise ValueError(f"Unsupported source adapter for {name}: {adapter}")
    return GenericSource(name=name, config=config, runtime_config=runtime_config)

