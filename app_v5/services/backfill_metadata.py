# app_v5/services/backfill_metadata.py
import sys
import os
import time
from pathlib import Path
import logging
import ast

# --- CORREÇÃO DEFINITIVA PARA O ModuleNotFoundError ---
# Adiciona o diretório raiz do projeto ao path para permitir importações.
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
# ----------------------------------------------------

# Importações de todas as fontes de metadados necessárias
from app_v5.database.db import conectar, fetch_musicas_sem_metadata, update_metadata_musica, _formatar_generos_para_db
from app_v5.integrations.spotify import enrich_from_spotify
from app_v5.integrations.deezer import search_deezer
from app_v5.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

log = logging.getLogger("FourierMatch_Backfill")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# --- Funções auxiliares para mesclar metadados ---
def _is_empty(v: any) -> bool:
    if v is None:
        return True
    v2 = str(v).strip().lower()
    return (v2 == "" or v2 in {"desconhecido", "nao encontrado", "não encontrado"})

def _merge_meta(dst: dict, src: dict, source_name: str):
    """Mescla os campos principais de um resultado de metadados para o dicionário de destino."""
    if not src:
        return
    log.info(f"  ↪️  Mesclando dados obtidos de [{source_name}]...")
    
    # Lista de campos para mesclar: (chave_na_fonte, chave_no_destino)
    campos_para_mesclar = {
        "title": "title", "artist": "artist", "album": "album",
        "cover": "cover", "link_spotify": "link_spotify"
    }
    
    for src_key, dst_key in campos_para_mesclar.items():
        if _is_empty(dst.get(dst_key)) and not _is_empty(src.get(src_key)):
            dst[dst_key] = src.get(src_key)

    # Tratamento especial para gêneros
    g = src.get("genres")
    if _is_empty(dst.get("genres")) and g:
        dst["genres"] = g
# ----------------------------------------------------

def rodar_backfill_com_failover():
    """
    Busca músicas com metadados faltando e tenta enriquecê-los usando
    Spotify e, como alternativa, a API do Deezer.
    """
    log.info("🚀 Iniciando processo de backfill de metadados com failover para Deezer...")

    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        log.error("!!! ATENÇÃO: Credenciais da API do Spotify não estão definidas. O script não pode continuar. !!!")
        return

    db_conn = None
    try:
        db_conn = conectar()
        musicas_para_corrigir = fetch_musicas_sem_metadata(db_conn)
        total = len(musicas_para_corrigir)
        log.info(f"🔍 Encontradas {total} músicas para enriquecer.")
        if total == 0:
            return

        sucesso, falha = 0, 0
        for i, musica in enumerate(musicas_para_corrigir, 1):
            id_musica = musica.get("id")
            titulo_atual = musica.get("titulo")
            artista_atual = musica.get("artista")
            
            log.info(f"[{i}/{total}] Processando ID {id_musica}: '{artista_atual} - {titulo_atual}'")
            
            meta_final = {"title": titulo_atual, "artist": artista_atual, "genres": None, "album": None}
            fonte_sucesso = ""

            # --- Camada 1: Spotify ---
            try:
                log.info("  1️⃣  Consultando Spotify...")
                sp_meta = enrich_from_spotify(artista_atual, titulo_atual, None, None)
                if sp_meta and sp_meta.get("accepted"):
                    _merge_meta(meta_final, sp_meta, "Spotify")
                    fonte_sucesso = "Spotify"
                else:
                    log.warning(f"  - Spotify não retornou dados confiáveis (motivo: {sp_meta.get('reason', 'N/A')}).")
            except Exception as e:
                log.error(f"  - Erro na chamada ao Spotify: {e}", exc_info=False) # exc_info=False para não poluir o log

            # --- Camada 2: Deezer (Failover) ---
            if not fonte_sucesso or _is_empty(meta_final.get("genres")):
                try:
                    log.info("  2️⃣  Consultando Deezer como alternativa...")
                    # A API do Deezer não retorna gêneros na busca, mas pode completar outras informações
                    q_fallback = f"{artista_atual} {titulo_atual}"
                    dz_meta = search_deezer(artista_atual, titulo_atual, None, q_fallback)
                    if dz_meta:
                        _merge_meta(meta_final, dz_meta, "Deezer")
                        # Deezer não é uma fonte de gênero, então só conta como sucesso se outra fonte já tiver dado o gênero
                        if not fonte_sucesso:
                           fonte_sucesso = "Deezer" # Pelo menos completou album/capa
                except Exception as e:
                    log.error(f"  - Erro na chamada ao Deezer: {e}", exc_info=False)

            # --- Atualização no Banco de Dados ---
            # A condição principal é ter conseguido um gênero válido
            if not _is_empty(meta_final.get("genres")):
                update_metadata_musica(
                    id_musica=id_musica,
                    novo_titulo=meta_final.get("title"),
                    novo_artista=meta_final.get("artist"),
                    novo_album=meta_final.get("album"),
                    novo_genero=meta_final.get("genres"),
                    nova_capa=meta_final.get("cover"),
                    novo_link_spotify=meta_final.get("link_spotify"),
                    db_conn=db_conn
                )
                log.info(f"  ✅ SUCESSO via [{fonte_sucesso}]! Gênero: {_formatar_generos_para_db(meta_final.get('genres'))}")
                sucesso += 1
            else:
                log.warning("  ⚠️ FALHA FINAL. Nenhuma fonte encontrou um gênero válido para esta música.")
                falha += 1

            time.sleep(0.5) # Pausa para não sobrecarregar as APIs

        log.info("🎉 Processo de backfill concluído!")
        log.info(f"Resultados: {sucesso} músicas atualizadas, {falha} falhas.")

    except Exception as e:
        log.error(f"❌ Ocorreu um erro catastrófico: {e}", exc_info=True)
    finally:
        if db_conn and db_conn.is_connected():
            db_conn.close()
            log.info("🔌 Conexão com o banco de dados fechada.")

if __name__ == "__main__":
    rodar_backfill_com_failover()