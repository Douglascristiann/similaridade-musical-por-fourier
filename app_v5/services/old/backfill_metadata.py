# app_v5/services/backfill_metadata.py
import sys
import os
import time
from pathlib import Path
import logging

# --- CORREÇÃO DEFINITIVA PARA O ModuleNotFoundError ---
# Adiciona o diretório raiz do projeto ao path para permitir importações.
# O script está em app_v5/services/, então a raiz está 2 níveis acima.
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
# ----------------------------------------------------

# Importações agora devem funcionar corretamente
from app_v5.database.db import conectar, fetch_musicas_sem_metadata, update_metadata_musica
from app_v5.integrations.spotify import enrich_from_spotify
from app_v5.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

log = logging.getLogger("FourierMatch_Backfill")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def rodar_backfill():
    """
    Busca músicas sem gênero ou álbum no banco de dados e tenta enriquecer
    seus metadados usando as informações disponíveis (título, artista) via Spotify.
    """
    log.info("🚀 Iniciando processo de backfill de metadados...")

    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        log.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        log.error("!!! ATENÇÃO: Credenciais da API do Spotify não estão    !!!")
        log.error("!!! definidas. O script não conseguirá buscar os dados.!!!")
        log.error("!!! Defina-as no arquivo .env ou como variáveis        !!!")
        log.error("!!! de ambiente.                                       !!!")
        log.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        return

    db_conn = None
    try:
        db_conn = conectar()
        if not db_conn:
            log.error("❌ Não foi possível conectar ao banco de dados.")
            return

        musicas_para_corrigir = fetch_musicas_sem_metadata(db_conn)
        total = len(musicas_para_corrigir)
        log.info(f"🔍 Encontradas {total} músicas para enriquecer.")

        if total == 0:
            log.info("✅ Nenhuma música com metadados faltando. Banco de dados está atualizado!")
            return

        sucesso = 0
        falha = 0
        for i, musica in enumerate(musicas_para_corrigir):
            id_musica = musica.get("id")
            titulo_atual = musica.get("titulo")
            artista_atual = musica.get("artista")

            log.info(f"[{i+1}/{total}] Processando ID: {id_musica} -> '{artista_atual} - {titulo_atual}'")

            try:
                # Usa a função de enriquecimento do Spotify que busca por artista e título
                md_enriquecido = enrich_from_spotify(
                    artist_hint=artista_atual,
                    title_hint=titulo_atual,
                    album_hint=None,
                    duration_sec=None
                )

                if md_enriquecido and md_enriquecido.get("accepted"):
                    # Argumentos na ordem correta
                    update_metadata_musica(
                        id_musica=id_musica,
                        novo_titulo=md_enriquecido.get("title", titulo_atual),
                        novo_artista=md_enriquecido.get("artist", artista_atual),
                        novo_album=md_enriquecido.get("album"),
                        novo_genero=md_enriquecido.get("genres"),
                        nova_capa=md_enriquecido.get("cover"),
                        novo_link_spotify=md_enriquecido.get("link_spotify"),
                        db_conn=db_conn
                    )
                    log.info(f"  ✅ SUCESSO! Gênero: {md_enriquecido.get('genres')}, Álbum: {md_enriquecido.get('album')}")
                    sucesso += 1
                else:
                    reason = md_enriquecido.get("reason", "sem correspondência")
                    log.warning(f"  ⚠️ FALHA. Não foi possível encontrar metadados confiáveis ({reason}).")
                    falha += 1

                # Pausa para não sobrecarregar a API do Spotify
                time.sleep(0.5)

            except Exception as e:
                log.error(f"  ❌ ERRO INESPERADO ao processar ID {id_musica}: {e}")
                falha += 1


        log.info("🎉 Processo de backfill concluído!")
        log.info(f"Resultados: {sucesso} musicas atualizadas, {falha} falhas.")

    except Exception as e:
        log.error(f"❌ Ocorreu um erro catastrófico durante o backfill: {e}", exc_info=True)
    finally:
        if db_conn and db_conn.is_connected():
            db_conn.close()
            log.info("🔌 Conexão com o banco de dados fechada.")

if __name__ == "__main__":
    rodar_backfill()