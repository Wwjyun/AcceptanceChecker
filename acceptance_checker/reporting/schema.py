# -*- coding: utf-8 -*-
"""Load packaged report schemas without importing a validator at runtime."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Dict


def load_formal_report_schema_v1() -> Dict[str, Any]:
    resource = resources.files("acceptance_checker.schemas").joinpath(
        "formal_report_v1.schema.json"
    )
    with resource.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError("formal report schema must be a JSON object")
    return data
