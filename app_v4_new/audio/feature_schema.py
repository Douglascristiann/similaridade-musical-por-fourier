# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
import json

SCHEMA_PATH = Path(__file__).resolve().parent / "feature_schema.json"

def load_schema(path: Path = SCHEMA_PATH):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return {"total": 161}
