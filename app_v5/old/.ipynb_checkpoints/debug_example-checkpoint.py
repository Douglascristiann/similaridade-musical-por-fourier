# app_v5/debug_example.py

from pathlib import Path
from app_v5.recom.knn_recommender import recomendar_por_audio
import logging
import sys
import os

# Garante que o diretório raiz esteja no path para importações corretas
try:
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
except Exception:
    pass

# Configura o logging para ver mensagens do processo, se houver
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- CONFIGURAÇÃO DO TESTE ---
# Coloque aqui o caminho para um arquivo de áudio que você queira usar como base
AUDIO_PATH_STR = "/home/jovyan/work/audio/Spinnin' Records - Disturbed - The Sound Of Silence (CYRIL Remix) [Official Audio]-uIBJJ3M76Mg.mp3"
# --- FIM DA CONFIGURAÇÃO ---


AUDIO = Path(AUDIO_PATH_STR).resolve()

if not AUDIO.exists():
    print(f"❌ ERRO: Arquivo de áudio não encontrado em: {AUDIO}")
    print("Por favor, edite o caminho da variável 'AUDIO_PATH_STR' no script 'app_v5/debug_example.py'.")
else:
    # --- TESTE COM DIFERENTES NÍVEIS DE RIGIDEZ ---
    for level in [0, 1, 2, 3]:
        print(f"\n========================================================================")
        print(f"   TESTANDO COM NÍVEL DE RIGIDEZ (strict_level) = {level}")
        print(f"   (0=Flexível, 1=Balanceado, 2=Rígido, 3=Muito Rígido)")
        print(f"========================================================================\n")
        
        recs = recomendar_por_audio(
            str(AUDIO),
            k=5,             # Número de recomendações desejadas
            sr=22050,        # Taxa de amostragem (manter padrão)
            strict_level=level, # <<< AQUI estamos variando o nível a cada iteração
            debug=True       # Forçar a geração de dados de debug
        )

        if not recs:
            print("Nenhuma recomendação encontrada para este nível de rigidez.")
            continue

        for r in recs:
            print(f"#{r['rank']:<2} | {r['titulo']} — {r['artista']}")
            d = r.get("debug", {})
            if d:
                # Extrai informações do debug para uma impressão mais clara
                dist = d.get('distance', 0)
                base = d.get('base_score', 0)
                pen = d.get('penalty_total', 0)
                final = d.get('final_like', 0)
                reasons = ", ".join(d.get("reasons", [])) or "Nenhuma penalidade"
                
                # Extrai gêneros para comparação
                query_genre = (d.get("query_sem") or {}).get("genre", "N/A")
                cand_genre = (d.get("cand_sem") or {}).get("genre", "N/A")
                
                print(f"   ├─ Score: dist={dist:.3f} | base={base:.3f} | pen={pen:.3f} | final={final:.3f}")
                print(f"   ├─ Gênero (Query -> Candidato): '{query_genre}' -> '{cand_genre}'")
                print(f"   └─ Razões da Penalidade: {reasons}")
            print("-" * 72)