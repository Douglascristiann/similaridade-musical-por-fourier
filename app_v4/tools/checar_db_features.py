
import sqlite3
import numpy as np
from pathlib import Path
from app_v4.config import EXPECTED_FEATURE_LENGTH
from app_v4.storage.db_utils import detect_table_and_cols

def _parse(s: str) -> np.ndarray:
    return np.fromstring(s, sep=',')

def run(db_path="musicas.db"):
    con = sqlite3.connect(db_path)
    table, m = detect_table_and_cols(con)
    cur = con.cursor()
    sel = f"SELECT {m['id']}, {m['features']} FROM {table}" if m['id'] else f"SELECT {m['features']} FROM {table}"
    cur.execute(sel)
    problems = []
    for row in cur.fetchall():
        if m['id']:
            _id, s = row
        else:
            _id, s = None, row[0]
        v = _parse(s)
        if EXPECTED_FEATURE_LENGTH is not None and v.size != EXPECTED_FEATURE_LENGTH:
            problems.append((_id, v.size))
    con.close()
    if problems:
        print("⚠️ Vectors with unexpected size:")
        for pid, sz in problems:
            print(f" - id={pid} size={sz} (expected={EXPECTED_FEATURE_LENGTH})")
    else:
        print("✅ All vectors have the expected size.")

if __name__ == "__main__":
    run()
