# processamento/processar_links.py

import sys
import os

# Garante acesso ao módulo da API
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "API")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "DB")))

from dowloadmusicyl import (
    reconhecer_titulo,
    inserir_links,
    ler_links_de_arquivo,
    baixar_musicas,
    limpar_arquivo
)
from db_connect import verificar_conexao_e_criar_tabela
from consulta_insercao import links_nao_existentes
#from discogs import processar_lista_titulos

def processar_link(link: str, caminho_arquivo_links: str, pasta_audio: str):

    try:
        verificar_conexao_e_criar_tabela()

        inserir_links(link, caminho_arquivo_links)
        lista_de_links = ler_links_de_arquivo(caminho_arquivo_links)
        links_novos = links_nao_existentes(lista_de_links)

        if not links_novos:
            print("⚠️ Todos os links já existem no banco de dados.")
            return 0
        if links_novos:
            total = baixar_musicas(links_novos, pasta_audio)
            metadados = reconhecer_titulo(links_novos)
            for i in range(len(metadados)):
                metadados[i]['link_youtube'] = links_novos[i]

            limpar_arquivo(caminho_arquivo_links)
            print(f"⬇️ Total de músicas baixadas: {total}")
            return metadados 
        else:
            print("❌ Nenhum link encontrado ou link inválido.")
            return 0
    except Exception as e:
    #     print(f"❌ Erro ao processar o link: {e}")
         return -1


