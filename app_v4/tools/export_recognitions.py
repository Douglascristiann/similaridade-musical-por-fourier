
import sqlite3, json
from pathlib import Path

def export_recognitions(db_path="musicas.db", out_path="recognitions.json"):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT file_hash, title, artist, album, isrc, source, confidence, raw_json, created_at FROM recognitions ORDER BY id DESC")
    rows = cur.fetchall()
    con.close()
    out = []
    for fh, title, artist, album, isrc, source, conf, raw, dt in rows:
        try:
            extra = json.loads(raw) if raw else {}
        except Exception:
            extra = {}
        out.append({
            "file_hash": fh, "title": title, "artist": artist, "album": album, "isrc": isrc,
            "source": source, "confidence": conf, "created_at": dt, **({"extra": extra} if extra else {})
        })
    Path(out_path).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Saved {len(out)} recognitions to {out_path}")

if __name__ == "__main__":
    export_recognitions()
