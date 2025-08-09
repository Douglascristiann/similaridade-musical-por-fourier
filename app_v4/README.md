
# FourierMatch (app_v5, PT-BR, MySQL)

**Universidade Paulista — Curso de Sistemas de Informação**  
**Criadores:** Douglas Cristian da Cunha (N7970A0), Fábio Silva Matos Filho (N8947E9)  
**TCC:** "Uma Abordagem Baseada em Análise Espectral para Recomendação Musical: Explorando a Transformada de Fourier como Alternativa aos Métodos Convencionais"

## O que mudou nesta versão
- Integração **MySQL** (usa seu `config.py` existente, se presente).
- Menu interativo com UX simples e logs suaves.
- YouTube com `yt-dlp` e `ffmpeg`, usando `cookies.txt` fixo em `/home/jovyan/work/cache/cookies/cookies.txt` (se existir).
- Ajustes deprecations: `librosa.feature.rhythm.tempo`, `shazamio.recognize`.
- Recomendação **Top-3** com **% de similaridade** (cosseno).
- HPSS, beat-sync, TIV-6, padronização por bloco + pesos (KNN coseno).

## Como rodar
```bash
pip install -r requirements.txt
# tenha ffmpeg e mysql rodando
python -m app_v5.main  # ou: python app_v5/main.py
```

> Se você tiver um `config.py` no projeto com `DB_CONFIG`, `DB_TABLE_NAME`, `AUDD_TOKEN`, `DISCOGS_TOKEN`, `EXPECTED_FEATURE_LENGTH`, o app usa automaticamente. Caso contrário, configure via variáveis de ambiente.

## Notas de DB
- Tabela: `tb_musicas_v4` (ou a definida no seu `config.py`).
- Vetor de features: por padrão **157** dims (esta versão); se seu `config.py` exigir outro tamanho (ex.: 161), o app **preenche com zeros** ou **trunca** para caber no seu banco.
