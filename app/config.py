# config.py

import os
# =================== CONFIGURAÇÃO ===================
DB_CONFIG = {
    "user": "root",
    "password": "managerffti8p68",
    "host": "db",
    "port": 3306,
    "database": "dbmusicadata"
}

AUDD_TOKEN = "194e979e8e5d531ffd6d54941f5b7977"

# Define o número esperado de características após a extração
# n_mfcc (40) * 3 (mfcc, delta, delta2) + chroma (12) + tonnetz (6) + contrast (7) + tempo (1)
EXPECTED_FEATURE_LENGTH = 40 * 3 + 12 + 6 + 6 + 1 + 1 + 1 + 1 + 1  # = 161

# Nome da tabela do banco de dados a ser usada
DB_TABLE_NAME = "tb_musicas_v3" # Usaremos a nova tabela v2

# Caminhos fixos
PASTA_SPECTROGRAMAS = "/home/jovyan/work/cache/spectrogramas"
PASTA_PLOT= "/home/jovyan/work/cache/recomendacoes_img"