"""Shared input validation for UCX sidecars.

Provides a lightweight validation layer that uses Pydantic when available
for rich type checking, with a no-op fallback when Pydantic is not installed.

Usage in a sidecar::

    from ucx_validate import validate_args, Field, Optional

    class ConvertArgs(BaseModel if HAS_PYDANTIC else object):
        input: str
        output: str
        quality: int = Field(default=18, ge=0, le=51)
        codec: str = "libx264"

    validated = validate_args(args_namespace, ConvertArgs)
    # validated is the original namespace if pydantic is unavailable,
    # or a validated model instance if pydantic is available.
"""
from __future__ import annotations

import sys
from typing import Any

HAS_PYDANTIC = False

try:
    from pydantic import BaseModel, Field, ValidationError
    from typing import Optional
    HAS_PYDANTIC = True
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def Field(**kwargs: Any) -> Any:
        return kwargs.get("default")

    class ValidationError(Exception):
        pass

    from typing import Optional


def validate_args(namespace: Any, model_cls: type, emit_fn: Any = None) -> Any:
    """Validate an argparse namespace against a Pydantic model.

    If Pydantic is available, constructs the model from the namespace dict
    and returns it. Validation errors are emitted as structured warnings
    via emit_fn (if provided) and the original namespace is returned.

    If Pydantic is not available, returns the namespace unchanged.
    """
    if not HAS_PYDANTIC or model_cls is BaseModel:
        return namespace

    try:
        data = vars(namespace) if hasattr(namespace, "__dict__") else namespace
        return model_cls(**data)
    except ValidationError as e:
        if emit_fn is not None:
            for err in e.errors():
                emit_fn("log", level="warn",
                        message=f"Input validation: {err['loc']}: {err['msg']}",
                        field=".".join(str(x) for x in err["loc"]),
                        error_type=err["type"])
        return namespace
    except Exception:
        return namespace
