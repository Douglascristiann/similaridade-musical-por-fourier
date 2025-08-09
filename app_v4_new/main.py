# -*- coding: utf-8 -*-
"""
Entry-point enxuto. Rode com:
    python3 app_v4_new/main.py
"""
import os, sys

PKG_DIR  = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PKG_DIR)
for p in (ROOT_DIR, PKG_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from app_v4_new.cli.menu import loop_interativo, print_header
from app_v4_new.database.db import criar_tabela

def main() -> int:
    print_header()
    criar_tabela()
    loop_interativo()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
