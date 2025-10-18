# Uma Abordagem Baseada em Análise Espectral para Recomendação Musical
**Explorando a Transformada de Fourier como alternativa aos métodos convencionais**

> Este repositório contém o **FourierMatch (app_v5)**, um protótipo modular de recomendação musical que compara faixas **pelo conteúdo sonoro**. O sistema extrai **161 medidas** por faixa (grupos de timbre, harmonia e ritmo), normaliza por blocos e estima similaridade via **KNN**. Há ingestão por **CLI** (arquivos locais/YouTube) e um **bot no Telegram** para coletar avaliações NPS (0–5).

---

## 📚 Sumário
- [Recursos principais](#-recursos-principais)
- [Arquitetura em alto nível](#-arquitetura-em-alto-nível)
- [Requisitos](#-requisitos)
- [Instalação local (venv)](#-instalação-local-venv)
- [Variáveis de ambiente (.env)](#-variáveis-de-ambiente-env)
- [Token do Telegram](#-token-do-telegram)
- [Spotify – API & Export de dados](#-spotify--api--export-de-dados)
- [Banco de Dados (MySQL)](#-banco-de-dados-mysql)
- [Execução (CLI e Bot)](#-execução-cli-e-bot)
- [Docker / Docker Compose](#-docker--docker-compose)
- [Ingestão YouTube (cookies)](#-ingestão-youtube-cookies)
- [Troubleshooting](#-troubleshooting)
- [Boas práticas de segurança](#-boas-práticas-de-segurança)
- [Estrutura do projeto](#-estrutura-do-projeto)

---

## ✨ Recursos principais
- Extração de **features espectrais** (timbre: MFCC etc.; harmonia: cromas/Tonnetz/contraste; ritmo: BPM/onsets).
- **Normalização em blocos** (reduz diferenças de escala/energia entre grupos de atributos).
- **KNN** para ranquear similaridade entre faixas.
- Integrações com **Spotify / Discogs / Shazam** para apoio de metadados/identificação.
- **CLI** para ingestão e operação.
- **Bot no Telegram** para avaliações NPS 0–5 e coleta de feedback de usuários.
- Persistência em **MySQL**.

---

## 🏛 Arquitetura em alto nível
```
app_v5/
  audio/                # extração FFT + features
  recom/                # KNN, preparação base escalada
  services/             # ingestão local/YouTube, metadata, backfills
  integrations/         # spotify, discogs, telegram bot, shazam
  database/             # conexão e rotinas MySQL
  cli/                  # menus e fluxo interativo
  config.py             # leitura de .env, paths padrão
  main.py               # entrada da CLI
```
> O nome `app_v5` é a versão atual modular. Evite alterar a estrutura de diretórios a menos que saiba o impacto nos imports.

---

## ✅ Requisitos
- **SO**: Linux, macOS ou Windows (WSL recomendado no Windows)
- **Python**: 3.11+ (3.12 recomendado)
- **MySQL**: 8.x (ou compatível)
- **FFmpeg** (binário no PATH) – exigido por `pydub` e útil com `yt-dlp`
- **libsndfile** – requerido por `soundfile`/`librosa`

Instalação rápida (Ubuntu/Debian):
```bash
sudo apt update
sudo apt install -y ffmpeg libsndfile1 mysql-client
```

Dependências Python (principais) – ver `requirements.txt`:
```
numpy
librosa
soundfile
python-dotenv>=1.0
requests
yt-dlp
mysql-connector-python
python-telegram-bot>=21.0
pydub>=0.25
shazamio
```

---

## 💻 Instalação local (venv)
```bash
# 1) Clone o repositório e entre na pasta
git clone <seu-repo>.git
cd <seu-repo>

# 2) Crie e ative o ambiente virtual
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scriptsctivate

# 3) Instale dependências
pip install -U pip
pip install -r requirements.txt

# 4) Garanta ffmpeg e libsndfile instalados (ver Requisitos)
# 5) Crie o arquivo .env (modelo abaixo)
```

---

## 🔐 Variáveis de ambiente (.env)
Crie um arquivo `.env` **na raiz** do projeto:

```dotenv
# --- App ---
APP_NAME=FourierMatch
APP_VERSION=5.0

# --- Banco de Dados ---
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=manager
DB_NAME=dbmusicadata
# Tabela principal de músicas (ajuste conforme seu schema)
DB_TABLE_NAME=tb_musicas_v4

# --- Telegram Bot ---
TELEGRAM_BOT_TOKEN=coloque_o_token_gerado_no_BotFather

# --- Spotify (Opção A: Client Credentials, metadados públicos) ---
SPOTIFY_CLIENT_ID=seu_client_id
SPOTIFY_CLIENT_SECRET=seu_client_secret
SPOTIFY_MARKET=BR

# --- Spotify (Opção B: OAuth de usuário, biblioteca/playlist privadas) ---
# Preencha se for ler biblioteca/playlist privada. Ver seção "Spotify – API & Export".
SPOTIFY_REDIRECT_URI=http://localhost:8080/callback
SPOTIFY_SCOPES=user-library-read,playlist-read-private
SPOTIFY_REFRESH_TOKEN=

# --- Discogs/Deezer (opcional) ---
DISCOGS_TOKEN=
DEEZER_APP_ID=
DEEZER_SECRET=

# --- YouTube / yt-dlp ---
# Caminho p/ cookies exportados do navegador (opcional, útil p/ vídeos restritos)
COOKIEFILE_PATH=./config/yt-cookies.txt

# --- Ingestão/Downloads ---
DOWNLOADS_DIR=./downloads
AUTO_DELETE_DOWNLOADED=false
```

> Dica: adicione um `.env.example` (sem segredos) ao versionamento para facilitar onboarding.

---

## 🤖 Token do Telegram
1. Abra o Telegram e converse com **@BotFather**.
2. Execute `/newbot` → defina **nome** e **username** (termina com `bot`).
3. Copie o **HTTP API token** exibido e coloque em `TELEGRAM_BOT_TOKEN` no `.env`.
4. Opcional: `/setprivacy` → **Disable** (se o bot atuar em grupos).
5. Opcional: `/setcommands` para registrar comandos do bot.

> Segurança: **nunca** publique este token. Se vazar, use `/revoke` e atualize o `.env`.

---

## 🎧 Spotify – API & Export de dados

### A) Client Credentials (metadados públicos)
1. Acesse <https://developer.spotify.com/dashboard> e crie um **App**.
2. Copie **Client ID** e **Client Secret** para o `.env`.
3. Defina `SPOTIFY_MARKET=BR` para preferências regionais.
4. **Não** requer redirect URI, scopes ou refresh token.

### B) OAuth de usuário (biblioteca/playlist privadas)
1. No **Dashboard** do Spotify, no seu App: em **Redirect URIs**, adicione  
   `http://localhost:8080/callback` (ou outro que você usar).
2. No `.env`, configure:
   - `SPOTIFY_REDIRECT_URI=http://localhost:8080/callback`
   - `SPOTIFY_SCOPES=user-library-read,playlist-read-private`
3. Obtenha um **Refresh Token** via fluxo de OAuth (script local ou ferramenta como Postman/Insomnia).
4. Preencha `SPOTIFY_REFRESH_TOKEN` no `.env`.

> Para **somente enriquecer metadados públicos**, geralmente **Client Credentials** é suficiente.

### C) Exportar seus dados (histórico/biblioteca)
1. Acesse <https://www.spotify.com/account/privacy/> → **Baixar seus dados**.
2. Solicite o pacote (pode levar alguns dias) e, quando receber, descompacte em:  
   `./data/spotify_export/` (sugestão de pasta).
3. Arquivos incluem histórico de streaming e biblioteca.  
   O uso no projeto depende dos scripts/rotinas que você optar por rodar.

---

## 🗄 Banco de Dados (MySQL)
Crie o banco e um usuário com permissões:
```sql
CREATE DATABASE IF NOT EXISTS dbmusicadata CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'fourier'@'%' IDENTIFIED BY 'troque_esta_senha';
GRANT ALL PRIVILEGES ON dbmusicadata.* TO 'fourier'@'%';
FLUSH PRIVILEGES;
```
Ajuste `DB_HOST/DB_USER/DB_PASSWORD/DB_NAME` no `.env`.

> **Schema**: o projeto costuma usar `tb_musicas_v4` (colunas como `id`, `nome`, `artista`,
> `titulo`, `album`, `genero`, `capa_album`, `features_json`, `created_at`, `updated_at`).  
> Adapte ao seu contexto e configure `DB_TABLE_NAME` no `.env`.

---

## ▶️ Execução (CLI e Bot)

### CLI principal
A partir da raiz do projeto:
```bash
# Modo módulo (recomendado)
python -m app_v5.main

# OU diretamente
python app_v5/main.py
```
Funções comuns:
- Ingestão de áudio local (WAV/MP3) → extrai 161 features e grava no MySQL
- Ingestão por YouTube (usa `yt-dlp`; cookies opcionais)
- Preparação/recalibração da base escalada
- Consulta/Recomendação via KNN

### Bot do Telegram
```bash
python app_v5/integrations/menu_bot.py
```
- Requer `TELEGRAM_BOT_TOKEN` válido.
- Coleta avaliações NPS (0–5) e preferências dos usuários.

---

## 🐳 Docker / Docker Compose
Crie um `docker-compose.yml` na raiz:

```yaml
version: "3.9"
services:
  db:
    image: mysql:8
    container_name: fm_db
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_PASSWORD:-manager}
      MYSQL_DATABASE: ${DB_NAME:-dbmusicadata}
      MYSQL_USER: ${DB_USER:-fourier}
      MYSQL_PASSWORD: ${DB_PASSWORD:-manager}
    ports:
      - "3306:3306"
    volumes:
      - db_data:/var/lib/mysql
    command: ["--default-authentication-plugin=mysql_native_password"]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 10

  app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: fm_app
    env_file: .env
    depends_on:
      - db
    volumes:
      - ./:/workspace
      - ./downloads:/workspace/downloads
      - ./config:/workspace/config
    working_dir: /workspace
    command: ["python", "-m", "app_v5.main"]

  bot:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: fm_bot
    env_file: .env
    depends_on:
      - db
    volumes:
      - ./:/workspace
      - ./downloads:/workspace/downloads
      - ./config:/workspace/config
    working_dir: /workspace
    command: ["python", "app_v5/integrations/menu_bot.py"]

volumes:
  db_data:
```

Crie um `Dockerfile` básico:
```dockerfile
FROM python:3.12-slim

# Dependências de sistema
RUN apt-get update && apt-get install -y --no-install-recommends     ffmpeg libsndfile1 gcc build-essential  && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Instala dependências Python (aproveita cache)
COPY requirements.txt .
RUN pip install -U pip && pip install -r requirements.txt

# Copia o projeto
COPY . .
```

Subindo serviços:
```bash
docker compose up -d --build
docker compose logs -f app     # logs da CLI
docker compose logs -f bot     # logs do bot
```

Executando comandos dentro do container:
```bash
docker compose exec app bash
python -m app_v5.main
```

---

## 🍪 Ingestão YouTube (cookies)
Alguns vídeos exigem cookies para baixar:
1. Exporte cookies do navegador (extensões como **Get cookies.txt**).
2. Salve em `./config/yt-cookies.txt` e ajuste `COOKIEFILE_PATH` no `.env`.
3. Rode a ingestão normalmente pela CLI.

---

## 🧪 Troubleshooting
- **`ffmpeg: command not found`** → Instale o binário e garanta que está no `PATH`.
- **`sndfile library not found` / erro ao importar `soundfile`** → Instale `libsndfile`.
- **MySQL `Access denied` / `Connection refused`** → Revise host/porta/credenciais e GRANTs.
- **`yt-dlp: Requested format is not available`** → Evite formatos rígidos; use cookies se necessário.
- **Telegram não responde** → Verifique `TELEGRAM_BOT_TOKEN` e se não há exceptions no log.

---

## 🔒 Boas práticas de segurança
- **Nunca** commitar `.env`, cookies ou tokens.
- Revogue tokens vazados imediatamente.
- Separe credenciais por ambiente (dev/stage/prod) e use `env_file` no Docker.

---

## 🗂 Estrutura do projeto
```
.
├─ app_v5/
├─ downloads/             # saída de áudios baixados (yt-dlp)
├─ config/
│  └─ yt-cookies.txt      # cookies exportados do navegador (opcional)
├─ data/
│  └─ spotify_export/     # pacote de dados exportados do Spotify (opcional)
├─ requirements.txt
├─ Dockerfile
├─ docker-compose.yml
├─ .env
└─ README.md
```
