"""Dynamic object loading helpers for ACBench agents."""

from __future__ import annotations

import importlib


def load_object(reference: str):
    """Load an object from a `module:qualname` reference."""

    if ":" not in reference:
        raise ValueError(
            f"Invalid object reference `{reference}`. Expected `module:qualname`."
        )
    module_name, qualname = reference.split(":", 1)
    module = importlib.import_module(module_name)
    obj = module
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj
