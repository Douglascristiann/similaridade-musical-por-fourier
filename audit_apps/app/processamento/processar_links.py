# processamento/processar_links.py

import sys
import os

# Garante acesso ao módulo da API
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "API")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "DB")))

from youtube import (
    inserir_links,
    ler_links_de_arquivo,
    baixar_musicas,
    limpar_arquivo
)
from db_connect import verificar_conexao_e_criar_tabela
from consulta_insercao import links_nao_existentes
from discogs import enriquecer_metadados_discogs

def processar_link(link: str, caminho_arquivo_links: str, pasta_audio: str):
    try:
        verificar_conexao_e_criar_tabela()

        inserir_links(link, caminho_arquivo_links)
        lista_de_links = ler_links_de_arquivo(caminho_arquivo_links)
        links_novos = links_nao_existentes(lista_de_links)

        if not links_novos:
            print("⚠️ Todos os links já existem no banco de dados.")
            return 0

        metadados = baixar_musicas(links_novos, pasta_audio)
        metadados = enriquecer_metadados_discogs(metadados)

        for i in range(len(metadados)):
            metadados[i]["link_youtube"] = links_novos[i]

        limpar_arquivo(caminho_arquivo_links)
        print(f"⬇️ Total de músicas baixadas: {len(links_novos)}")
        return metadados

    except Exception as e:
        print(f"❌ Erro ao processar link: {e}")
        return -1


