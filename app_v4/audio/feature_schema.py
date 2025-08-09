
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import numpy as np

SCHEMA_PATH = Path(__file__).resolve().parent / "feature_schema.json"

@dataclass(frozen=True)
class BlockSpec:
    name: str

# Ordem dos blocos no vetor final
FEATURE_ORDER = [
    BlockSpec("mfcc"),
    BlockSpec("mfcc_delta"),
    BlockSpec("mfcc_delta2"),
    BlockSpec("spectral_contrast"),
    BlockSpec("chroma_h_ci"),
    BlockSpec("tiv6"),
    BlockSpec("tonnetz_h"),
    BlockSpec("zcr_p"),
    BlockSpec("centroid_p"),
    BlockSpec("bandwidth_p"),
    BlockSpec("rolloff_p"),
    BlockSpec("tempo_bpm"),
    BlockSpec("tempo_var"),
]

def stack_features(blocks: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, int]]:
    parts, lens = [], {}
    for spec in FEATURE_ORDER:
        if spec.name not in blocks:
            raise KeyError(f"Bloco de feature ausente: {spec.name}. Recebidos: {list(blocks.keys())}")
        a = np.asarray(blocks[spec.name]).ravel()
        lens[spec.name] = a.size
        parts.append(a)
    vec = np.concatenate(parts, axis=0) if parts else np.array([], dtype=float)
    return vec, lens

def save_schema_if_missing(lens: dict[str, int], path: Path = SCHEMA_PATH) -> None:
    if not path.exists():
        data = {"order": [b.name for b in FEATURE_ORDER],
                "lengths": {k: int(v) for k, v in lens.items()},
                "total": int(sum(lens.values()))}
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def load_schema(path: Path = SCHEMA_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())

def assert_against_schema(total_len: int, lens: dict[str, int], path: Path = SCHEMA_PATH) -> None:
    schema = load_schema(path)
    if not schema:
        save_schema_if_missing(lens, path)
        return
    expected_order = schema["order"]
    current_order = [b.name for b in FEATURE_ORDER]
    if current_order != expected_order:
        raise AssertionError(f"Ordem dos blocos mudou.\nEsperado: {expected_order}\nAtual:   {current_order}")
    expected_lens = schema["lengths"]
    diffs = {k: (lens.get(k), expected_lens.get(k)) for k in expected_lens if lens.get(k) != expected_lens.get(k)}
    if diffs:
        det = "\n".join([f"- {k}: atual={v[0]} esperado={v[1]}" for k, v in diffs.items()])
        raise AssertionError(f"Tamanhos dos blocos divergiram:\n{det}")
    if total_len != int(schema["total"]):
        raise AssertionError(f"Tamanho total divergente: atual={total_len} esperado={schema['total']}")
