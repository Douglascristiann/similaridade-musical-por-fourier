# API/reconhecimento_unificado.py

import asyncio
from API.reconhecimento_shazam   import reconhecer_shazam_trechos
from API.reconhecimento_audd     import reconhecer_audd
from API.reconhecimento_metadado import reconhecer_metadado

async def reconhecer_musica(path):
    res = await reconhecer_shazam_trechos(path)
    if res: return res
    print("⚠️ Shazam falhou, tentando AudD…")
    res2 = reconhecer_audd(path)
    if any(r!="Não Encontrado" for r in res2): return res2
    return reconhecer_metadado(path)
