# app_v5/services/backfill_metadata.py
import sys
from pathlib import Path
import time
import logging
import re

# Adiciona o diretório raiz ao path para encontrar outros módulos
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from app_v5.database.db import fetch_musicas_sem_metadata, update_metadata_musica, conectar
from app_v5.integrations.spotify import enrich_from_spotify
from app_v5.integrations.deezer import enrich_from_deezer # <-- Importa a nova função

# Configuração do logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)


def parse_titulo_sujo(artista_original: str, titulo_original: str) -> tuple[str, str]:
    if artista_original and artista_original.lower() != 'desconhecido':
        return artista_original, titulo_original
    match = re.match(r'^(.*?)\s*[-–]\s*(.*)', titulo_original)
    if match:
        artista_extraido, titulo_limpo = match.groups()
        titulo_limpo = re.sub(r'(-[a-zA-Z0-9_]{11})$', '', titulo_limpo).strip()
        return artista_extraido.strip(), titulo_limpo
    return artista_original, titulo_original


def backfill_missing_genres():
    log.info("Iniciando o processo de backfill de metadados...")
    db_conn = None
    try:
        db_conn = conectar()
        if not db_conn:
            log.error("🚨 Não foi possível conectar ao banco de dados.")
            return

        musicas_para_atualizar = fetch_musicas_sem_metadata(db_conn=db_conn)
        if not musicas_para_atualizar:
            log.info("🎉 Nenhuma música para atualizar.")
            return

        log.info(f"Encontradas {len(musicas_para_atualizar)} músicas para atualizar.")
        
        sucesso = 0
        falhas = 0
        sem_genero_em_ambos = 0

        for musica in musicas_para_atualizar:
            musica_id = musica.get('id')
            artista_db = musica.get('artista', 'desconhecido')
            titulo_db = musica.get('titulo', '')

            artista_limpo, titulo_limpo = parse_titulo_sujo(artista_db, titulo_db)
            
            if not artista_limpo or not titulo_limpo:
                log.warning(f"⏭️ Pulando ID {musica_id} por falta de artista ou título.")
                continue
                
            log.info(f"🔄 Processando ID {musica_id}: '{artista_limpo} - {titulo_limpo}'...")

            try:
                # --- TENTATIVA 1: SPOTIFY ---
                spotify_data = enrich_from_spotify(artista_limpo, titulo_limpo, musica.get('album'), None)
                
                genres = None
                if spotify_data and spotify_data.get("accepted"):
                    # Pega os gêneros do Spotify, se existirem
                    genres = spotify_data.get("genres") if spotify_data.get("genres") else None

                # --- TENTATIVA 2: DEEZER (FALLBACK) ---
                if not genres:
                    log.info(f"   ↪ Spotify não retornou gênero. Tentando Deezer...")
                    deezer_data = enrich_from_deezer(artista_limpo, titulo_limpo)
                    if deezer_data:
                        genres = deezer_data.get("genres")

                # --- LÓGICA DE ATUALIZAÇÃO ---
                if genres:
                    # Usa os dados do Spotify se disponíveis, pois são mais completos
                    fonte_dados = spotify_data if spotify_data and spotify_data.get("accepted") else {}
                    update_metadata_musica(
                        id_musica=musica_id,
                        novo_titulo=fonte_dados.get("title", titulo_limpo),
                        novo_artista=fonte_dados.get("artist", artista_limpo),
                        novo_album=fonte_dados.get("album"),
                        novo_genero=genres,
                        nova_capa=fonte_dados.get("cover"),
                        novo_link_spotify=fonte_dados.get("link_spotify"),
                        db_conn=db_conn
                    )
                    log.info(f"✔ ID {musica_id} atualizado com sucesso. Gêneros: {', '.join(genres)}")
                    sucesso += 1
                else:
                    # Se chegou aqui, nem Spotify nem Deezer retornaram gênero
                    log.warning(f"ℹ️ Não foi encontrado gênero no Spotify ou na Deezer para '{artista_limpo} - {titulo_limpo}'. O registro não será alterado.")
                    sem_genero_em_ambos += 1
                
                time.sleep(1)

            except Exception as e:
                log.error(f"🚨 Erro grave ao processar a música ID {musica_id}: {e}")
                falhas += 1
                continue
    
    finally:
        if db_conn and db_conn.is_connected():
            db_conn.close()
            log.info("Conexão com o banco de dados fechada.")

    log.info("🎉 Processo finalizado!")
    log.info(f"Resultados: {sucesso} músicas atualizadas, {falhas} falhas de busca, {sem_genero_em_ambos} encontradas sem gênero em ambas as fontes.")


if __name__ == "__main__":
    backfill_missing_genres()