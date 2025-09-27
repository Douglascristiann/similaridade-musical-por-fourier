# debug_example.py  (na raiz do projeto)
# Em app_v5/debug_example.py

from pathlib import Path
from app_v5.recom.knn_recommender import recomendar_por_audio # A importação estava incorreta no seu arquivo

# caminho do áudio de teste
AUDIO = Path("/home/jovyan/work/audio/MC Menor JP, RAMONMIX, The Ironix - Menina de Vermelho-k3KaGdFNwlY.mp3").resolve()

recs = recomendar_por_audio(
    str(AUDIO),
    k=5,
    sr=22050,          # <-- ADICIONE ESTA LINHA
    strict_level=2,
    debug=True
)
# ... resto do script

for r in recs:
    print(f"#{r['rank']}  {r['titulo']} — {r['artista']}")
    d = r.get("debug", {})
    if d:
        reasons = ", ".join(d.get("reasons", [])) or "-"
        print(f"   dist={d['distance']:.3f}  base={d['base_score']:.3f}  "
              f"pen={d['penalty_total']:.3f}  final={d['final_like']:.3f}")
        print(f"   reasons: {reasons}")
        print(f"   query:  {d.get('query_sem')}")
        print(f"   cand:   {d.get('cand_sem')}")
    print("-"*72)
