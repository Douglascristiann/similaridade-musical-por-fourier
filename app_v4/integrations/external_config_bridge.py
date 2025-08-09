
from __future__ import annotations
import os
import importlib
from typing import Any, Dict, Optional

DEFAULT_TABLE = "tb_musicas_v4"
DEFAULT_EXPECTED_LEN = 157  # comprimento padrão do vetor do extrator desta versão

def load_external_config() -> Dict[str, Any]:
    """
    Tenta importar um módulo 'config' externo (o seu atual) para pegar:
      - DB_CONFIG (MySQL), DB_TABLE_NAME, AUDD_TOKEN, DISCOGS_TOKEN, EXPECTED_FEATURE_LENGTH
    Se não existir, usa variáveis de ambiente e defaults.
    """
    cfg: Dict[str, Any] = {}
    try:
        ext = importlib.import_module("config")
        cfg["DB_CONFIG"] = getattr(ext, "DB_CONFIG")
        cfg["DB_TABLE_NAME"] = getattr(ext, "DB_TABLE_NAME", DEFAULT_TABLE)
        cfg["AUDD_TOKEN"] = getattr(ext, "AUDD_TOKEN", os.getenv("AUDD_API_TOKEN", ""))
        cfg["DISCOGS_TOKEN"] = getattr(ext, "DISCOGS_TOKEN", os.getenv("DISCOGS_TOKEN", ""))
        cfg["EXPECTED_FEATURE_LENGTH"] = getattr(ext, "EXPECTED_FEATURE_LENGTH", DEFAULT_EXPECTED_LEN)
    except Exception:
        # Fallback para env vars
        cfg["DB_CONFIG"] = {
            "user": os.getenv("DB_USER", "root"),
            "password": os.getenv("DB_PASSWORD", ""),
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", "3306")),
            "database": os.getenv("DB_NAME", "dbmusicadata"),
        }
        cfg["DB_TABLE_NAME"] = os.getenv("DB_TABLE_NAME", DEFAULT_TABLE)
        cfg["AUDD_TOKEN"] = os.getenv("AUDD_API_TOKEN", "")
        cfg["DISCOGS_TOKEN"] = os.getenv("DISCOGS_TOKEN", "")
        try:
            cfg["EXPECTED_FEATURE_LENGTH"] = int(os.getenv("EXPECTED_FEATURE_LENGTH", str(DEFAULT_EXPECTED_LEN)))
        except Exception:
            cfg["EXPECTED_FEATURE_LENGTH"] = DEFAULT_EXPECTED_LEN
    return cfg
