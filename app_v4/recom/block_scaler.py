
from __future__ import annotations
from pathlib import Path
import numpy as np
from ..audio.feature_schema import load_schema, SCHEMA_PATH

class BlockStandardizer:
    def __init__(self, order: list[str], lengths: dict[str, int]):
        self.order = order
        self.lengths = {k: int(v) for k, v in lengths.items()}
        self.slices: dict[str, slice] = {}
        start = 0
        for name in self.order:
            L = self.lengths[name]
            self.slices[name] = slice(start, start + L)
            start += L
        self.total = start
        self.mu: np.ndarray | None = None
        self.sigma: np.ndarray | None = None

    def fit(self, X: np.ndarray) -> "BlockStandardizer":
        if X.shape[1] != self.total:
            raise ValueError(f"X dim={X.shape[1]} differs from schema={self.total}")
        mu_parts, sg_parts = [], []
        for name in self.order:
            sl = self.slices[name]
            B = X[:, sl]
            mu = B.mean(axis=0)
            sg = B.std(axis=0)
            sg[sg < 1e-8] = 1.0
            mu_parts.append(mu)
            sg_parts.append(sg)
        self.mu = np.concatenate(mu_parts, axis=0).astype(np.float32)
        self.sigma = np.concatenate(sg_parts, axis=0).astype(np.float32)
        return self

    def _check(self):
        if self.mu is None or self.sigma is None:
            raise RuntimeError("Scaler not fitted. Call fit() or load().")

    def transform_matrix(self, X: np.ndarray, weights: dict[str, float] | None = None) -> np.ndarray:
        self._check()
        Xs = (X - self.mu) / self.sigma
        if weights:
            for name, w in weights.items():
                if name in self.slices:
                    Xs[:, self.slices[name]] *= float(w)
        return Xs

    def transform_vector(self, x: np.ndarray, weights: dict[str, float] | None = None) -> np.ndarray:
        self._check()
        xs = (x - self.mu) / self.sigma
        if weights:
            for name, w in weights.items():
                if name in self.slices:
                    xs[self.slices[name]] *= float(w)
        return xs

    def save(self, path: Path):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            mu=self.mu, sigma=self.sigma,
            order=np.array(self.order, dtype="U"),
            lengths=np.array([self.lengths[n] for n in self.order], dtype=np.int32),
        )

    @classmethod
    def load(cls, path: Path) -> "BlockStandardizer":
        data = np.load(Path(path), allow_pickle=True)
        order = list(data["order"].tolist())
        lens_list = list(map(int, data["lengths"].tolist()))
        lengths = {name: L for name, L in zip(order, lens_list)}
        obj = cls(order, lengths)
        obj.mu = data["mu"].astype(np.float32)
        obj.sigma = data["sigma"].astype(np.float32)
        return obj

def load_schema_standardizer(schema_path: Path = SCHEMA_PATH) -> BlockStandardizer:
    schema = load_schema(schema_path)
    if not schema:
        raise RuntimeError("Feature schema not found. Extract at least one track to generate it.")
    order = list(schema["order"])
    lengths = {k: int(v) for k, v in schema["lengths"].items()}
    return BlockStandardizer(order, lengths)

def fit_and_save_scaler(X: np.ndarray, save_path: Path, schema_path: Path = SCHEMA_PATH) -> BlockStandardizer:
    scaler = load_schema_standardizer(schema_path)
    scaler.fit(X)
    scaler.save(save_path)
    return scaler

def load_or_fit_scaler(X: np.ndarray, save_path: Path) -> BlockStandardizer:
    path = Path(save_path)
    if path.exists():
        return BlockStandardizer.load(path)
    return fit_and_save_scaler(X, save_path)
