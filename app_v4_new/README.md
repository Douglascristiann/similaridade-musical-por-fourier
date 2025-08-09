
# app_v4_new — PT-BR, MySQL (usa seu config.py e cria tabela nova)

Este pacote conecta **direto no seu banco** usando **seu `config.py`** (DB_CONFIG, EXPECTED_FEATURE_LENGTH)
e cria **uma nova tabela em português** `tb_musicas_fourier` para não conflitar com a base antiga.

- **db.py** no formato que você já usa (conexão via `DB_CONFIG` do `config.py`, e inserção baseada em CSV de features).  
  Referência do seu estilo anterior de `db.py` e `config.py`.  
- **3 recomendações** em **%** (coseno) após cada ingestão.
- **YouTube** com `yt-dlp` e `cookiefile` fixo `/home/jovyan/work/cache/cookies/cookies.txt` (se não existir, avisa e segue).
- **Features**: LUFS/RMS, HPSS, beat-sync, MFCC(+Δ,+Δ²), Spectral Contrast, Chroma alinhado, **TIV‑6**, Tonnetz, ZCR/centroid/bandwidth/rolloff, tempo/variância.

## Como rodar
```bash
pip install -r requirements.txt
python -m app_v4_new
# ou
python app_v4_new/main.py
```

> Garanta que exista um `config.py` na **raiz do projeto** com `DB_CONFIG` e `EXPECTED_FEATURE_LENGTH`.
> A nova tabela criada é `tb_musicas_fourier`. Para trocar, exporte `DB_TABELA_NOVA=nome_que_você_quiser`.

## Observação sobre o tamanho do vetor
- Esta versão gera **157** dimensões. Se no seu `config.py` `EXPECTED_FEATURE_LENGTH=161`, o app **preenche com zeros**
  para chegar em 161 antes de gravar (e filtra por esse tamanho ao carregar). Assim mantém compatibilidade.
