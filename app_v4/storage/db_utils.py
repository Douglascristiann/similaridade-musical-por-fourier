
from __future__ import annotations
from pathlib import Path
import sqlite3
from typing import Dict, List, Optional, Tuple
import numpy as np
import json

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".aiff", ".aif"}

def default_db_path() -> Path:
    cwd = Path.cwd() / "musicas.db"
    if cwd.exists():
        return cwd
    repo_root = Path(__file__).resolve().parents[2] / "musicas.db"
    if repo_root.exists():
        return repo_root
    return Path(__file__).resolve().parents[1] / "musicas.db"

# ---------------- Schema e detecção ----------------

def ensure_schema(db_path: str | Path) -> None:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    exists_any = cur.fetchone()[0] > 0
    if not exists_any:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS musicas (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              titulo TEXT,
              artista TEXT,
              caminho TEXT,
              caracteristicas TEXT NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_musicas_titulo ON musicas (titulo)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_musicas_artista ON musicas (artista)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_musicas_caminho ON musicas (caminho)")
        con.commit()
    # cache de reconhecimento
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS recognitions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          file_hash TEXT UNIQUE,
          title TEXT,
          artist TEXT,
          album TEXT,
          isrc TEXT,
          source TEXT,
          confidence REAL,
          raw_json TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    con.commit()
    con.close()

def detect_table_and_cols(con: sqlite3.Connection) -> tuple[str, Dict[str, str]]:
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    if not tables:
        raise RuntimeError("Nenhuma tabela encontrada. Rode 'indexar' para criar/popular o banco.")
    candidates = [t for t in tables if any(x in t.lower() for x in ("musica", "song", "track"))]
    table = candidates[0] if candidates else tables[0]

    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]

    def pick(*keys):
        for k in keys:
            for c in cols:
                if k in c.lower():
                    return c
        return None

    mapping = {
        "id":        pick("id"),
        "titulo":    pick("titulo", "title", "nome"),
        "artista":   pick("artista", "artist"),
        "caminho":   pick("caminho", "arquivo", "file", "path"),
        "features":  pick("caracter", "feature", "vetor"),
        "created_at":pick("created_at", "data", "dt"),
    }
    if mapping["features"] is None:
        raise RuntimeError(f"Coluna de features não localizada na tabela '{table}'. Colunas: {cols}")
    return table, mapping

# ---------------- Conversões ----------------

def vec_to_str(vec: np.ndarray) -> str:
    v = np.asarray(vec).ravel().astype(float)
    return ",".join(f"{x:.9g}" for x in v)

def str_to_vec(s: str) -> np.ndarray:
    return np.fromstring(s, sep=',')

# ---------------- Operações de música ----------------

def musica_existe(con: sqlite3.Connection, table: str, mapping: Dict[str, str],
                  titulo: Optional[str], artista: Optional[str], caminho: Optional[str]) -> Optional[int]:
    cur = con.cursor()
    if caminho and mapping["caminho"]:
        cur.execute(f"SELECT {mapping['id']} FROM {table} WHERE {mapping['caminho']} = ?", (caminho,))
        r = cur.fetchone()
        if r:
            return int(r[0])
    if titulo and artista and mapping["titulo"] and mapping["artista"]:
        cur.execute(
            f"""
            SELECT {mapping['id']} FROM {table}
            WHERE lower({mapping['titulo']}) = lower(?) AND lower({mapping['artista']}) = lower(?)
            """,
            (titulo, artista),
        )
        r = cur.fetchone()
        if r:
            return int(r[0])
    return None

def insert_track(db_path: str | Path, titulo: str, artista: str, caminho: Optional[str], vec: np.ndarray,
                 upsert: bool = True) -> int:
    ensure_schema(db_path)
    con = sqlite3.connect(str(db_path))
    table, m = detect_table_and_cols(con)

    existing_id = musica_existe(con, table, m, titulo, artista, caminho)
    cur = con.cursor()
    if existing_id and upsert:
        cur.execute(
            f"UPDATE {table} SET {m['features']} = ?, {m['titulo']} = ?, {m['artista']} = ?, {m['caminho']} = ? WHERE {m['id']} = ?",
            (vec_to_str(vec), titulo, artista, caminho, existing_id),
        )
        con.commit()
        con.close()
        return int(existing_id)

    cols = []
    vals = []
    ph = []
    if m["titulo"]:
        cols += [m["titulo"]]; vals += [titulo]; ph += ["?"]
    if m["artista"]:
        cols += [m["artista"]]; vals += [artista]; ph += ["?"]
    if m["caminho"]:
        cols += [m["caminho"]]; vals += [caminho]; ph += ["?"]
    cols += [m["features"]]; vals += [vec_to_str(vec)]; ph += ["?"]

    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(ph)})"
    cur.execute(sql, tuple(vals))
    new_id = int(cur.lastrowid)
    con.commit()
    con.close()
    return new_id

def load_feature_matrix(db_path: str | Path) -> tuple[np.ndarray, List[int], List[Dict[str, str]]]:
    con = sqlite3.connect(str(db_path))
    table, m = detect_table_and_cols(con)
    cur = con.cursor()
    cols = [m["id"], m["titulo"], m["artista"], m["caminho"], m["features"]]
    cols = [c for c in cols if c is not None]
    cur.execute(f"SELECT {', '.join(cols)} FROM {table}")
    ids, metas, rows = [], [], []
    for row in cur.fetchall():
        row = list(row)
        feats = str_to_vec(row[-1])
        rows.append(feats)
        meta = {}
        if m["id"] in cols:      meta["id"] = row[cols.index(m["id"])]
        if m["titulo"] in cols:  meta["titulo"] = row[cols.index(m["titulo"])]
        if m["artista"] in cols: meta["artista"] = row[cols.index(m["artista"])]
        if m["caminho"] in cols: meta["caminho"] = row[cols.index(m["caminho"])]
        metas.append(meta)
        ids.append(meta.get("id", len(ids)))
    con.close()
    if not rows:
        raise RuntimeError("Banco vazio. Indexe algumas faixas primeiro.")
    X = np.vstack(rows).astype(np.float32)
    return X, ids, metas

def list_tracks(db_path: str | Path, limit: int = 20) -> List[Dict[str, str]]:
    con = sqlite3.connect(str(db_path))
    table, m = detect_table_and_cols(con)
    cur = con.cursor()
    cols = [m["id"], m["titulo"], m["artista"], m["caminho"], m["created_at"]]
    cols = [c for c in cols if c is not None]
    cur.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {m['id']} DESC LIMIT ?", (limit,))
    out = []
    for row in cur.fetchall():
        d = {}
        for c, v in zip(cols, row):
            d[c] = v
        out.append(d)
    con.close()
    return out

# ---------------- Cache de reconhecimento ----------------

def upsert_recognition(db_path: str | Path, file_hash: str, payload: dict) -> None:
    ensure_schema(db_path)
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    raw_json = json.dumps(payload, ensure_ascii=False)
    cur.execute("SELECT id FROM recognitions WHERE file_hash = ?", (file_hash,))
    r = cur.fetchone()
    values = (
        file_hash,
        payload.get("title"),
        payload.get("artist"),
        payload.get("album"),
        payload.get("isrc"),
        payload.get("source"),
        float(payload.get("confidence", 0.0)),
        raw_json,
    )
    if r:
        cur.execute(
            f"UPDATE recognitions SET title=?, artist=?, album=?, isrc=?, source=?, confidence=?, raw_json=? WHERE file_hash=?",
            (values[1], values[2], values[3], values[4], values[5], values[6], values[7], file_hash),
        )
    else:
        cur.execute(
            f"INSERT INTO recognitions (file_hash, title, artist, album, isrc, source, confidence, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )
    con.commit()
    con.close()

def get_recognition(db_path: str | Path, file_hash: str) -> Optional[dict]:
    ensure_schema(db_path)
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute("SELECT title, artist, album, isrc, source, confidence, raw_json FROM recognitions WHERE file_hash = ?", (file_hash,))
    r = cur.fetchone()
    con.close()
    if not r:
        return None
    title, artist, album, isrc, source, conf, raw_json = r
    try:
        extra = json.loads(raw_json) if raw_json else {}
    except Exception:
        extra = {}
    return {"title": title, "artist": artist, "album": album, "isrc": isrc, "source": source, "confidence": conf, **extra}
