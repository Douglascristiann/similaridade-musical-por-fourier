
# FourierMatch (app_v4) — PORTUGUÊS

Similaridade musical + pipeline de reconhecimento com cache — 100% em português.

## Destaques
- **Features “Fourier-friendly”**: normalização de loudness (LUFS/RMS), HPSS, agregação sincronizada ao pulso, MFCC(+Δ,+Δ²), Spectral Contrast, chroma harmônico **alinhado (invariante a transposição)** + **TIV‑6** (DFT), Tonnetz, ZCR/centroid/bandwidth/rolloff, tempo/variância.
- **Recomendador**: KNN com cosseno + **padronização por bloco** e pesos.
- **Reconhecimento**: Shazam *(via `shazamio`, opcional)* → **AudD** → enriquecimento **Discogs**; tudo com **cache** em SQLite.
- **CLI** com comandos em português (mantidos **aliases** em inglês).

## Instalação
```bash
pip install -r requirements.txt
```

### Variáveis de ambiente (.env opcional)
Crie um `.env` na raiz (ou exporte no shell):
```env
AUDD_API_TOKEN=coloque_sua_chave
DISCOGS_TOKEN=coloque_seu_token
SHAZAM_ENABLE=true
```
> Sem `shazamio` ou com `SHAZAM_ENABLE=false`, o pipeline usa apenas AudD → Discogs.

## Como usar

**Indexar** (extrair features; com `--enriquecer` faz reconhecimento e preenche título/artista):
```bash
python -m app_v4.main indexar ./dataset -r --enriquecer
# alias em inglês: python -m app_v4.main ingest ./dataset -r --enrich
```

**Reconhecer** metadados (sem indexar):
```bash
python -m app_v4.main reconhecer ./dataset --json
# alias: recognize
```

**Recomendar por id**:
```bash
python -m app_v4.main recomendar-id 1 --k 10
# alias: recommend-id
```

**Recomendar por arquivo**:
```bash
python -m app_v4.main recomendar-arquivo ./dataset/uma_faixa.wav --k 10
# alias: recommend-file
```

**Reajustar o scaler por bloco** (após crescer a base):
```bash
python -m app_v4.main normalizador reajustar
# alias: scaler rebuild
```

**Listar itens do banco**:
```bash
python -m app_v4.main banco listar --limite 20
# alias: db list
```

**Sobre**:
```bash
python -m app_v4.main sobre
# alias: about
```

## Observações
- No primeiro run de extração, será criado `app_v4/audio/feature_schema.json` com a composição e o tamanho do vetor de features.
- A tabela `recognitions` guarda **cache** por hash (SHA‑1) do arquivo.
- Os **pesos por bloco** ficam em `app_v4/config.py` (`BLOCK_WEIGHTS`). Ajuste e rode `normalizador reajustar`.
