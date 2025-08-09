
# FourierMatch (app_v4) — COMPLETO

Similaridade musical + pipeline de reconhecimento com cache.

## Destaques
- **Features Fourier-friendly**: LUFS/RMS, HPSS, beat-synchronous, MFCC(+Δ,+Δ²), Spectral Contrast, Chroma alinhado (key-invariant) + **TIV‑6** (DFT), Tonnetz, ZCR/centroid/bandwidth/rolloff, tempo/variância.
- **Recomendador**: Cosine KNN + **padronização por bloco** com pesos.
- **Reconhecimento**: Shazam *(via `shazamio`, opcional)* → **AudD** → enriquecimento **Discogs**; todos com **cache** em SQLite.
- **CLI** de produto (`ingest`, `recognize`, `recommend-*`, `scaler`, `db`).

## Instalação
```bash
pip install -r requirements.txt
```

### Variáveis de ambiente (.env opcional)
Crie um `.env` na raiz do projeto (ou exporte no shell):
```env
AUDD_API_TOKEN=coloque_sua_chave
DISCOGS_TOKEN=coloque_seu_token
SHAZAM_ENABLE=true
```

## Uso
Ingerir e **enriquecer metadados**:
```bash
python -m app_v4.main ingest ./dataset -r --enrich
```

Reconhecer metadados (sem ingerir):
```bash
python -m app_v4.main recognize ./dataset --json
```

Recomendar por **id**:
```bash
python -m app_v4.main recommend-id 1 --k 10
```

Recomendar por **arquivo**:
```bash
python -m app_v4.main recommend-file ./dataset/uma_faixa.wav --k 10
```

Reajustar scaler bloqueado:
```bash
python -m app_v4.main scaler rebuild
```

Listar itens do banco:
```bash
python -m app_v4.main db list --limit 20
```

## Observações
- No primeiro run de extração, será criado `app_v4/audio/feature_schema.json` com composição/tamanho do vetor.
- `recognitions` guarda cache por hash do arquivo (SHA‑1). Alterou o arquivo? O hash muda, o cache refaz.
- **Shazam** requer `shazamio`; se não quiser usar, defina `SHAZAM_ENABLE=false` (ou não instale `shazamio`) e o pipeline cai direto no **AudD**.
- **Discogs** usa token de acesso (veja a doc oficial para gerar).

