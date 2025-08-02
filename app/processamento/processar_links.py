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
from consulta_insercao import musicas_nao_existentes

def processar_link(link: str, caminho_arquivo_links: str, pasta_audio: str):

    try:
        verificar_conexao_e_criar_tabela()

        inserir_links(link, caminho_arquivo_links)
        lista_de_links = ler_links_de_arquivo(caminho_arquivo_links)
        r = reconhecer_titulo(lista_de_links)

        lista_de_links = musicas_nao_existentes(r)

        if lista_de_links:
            total = baixar_musicas(lista_de_links, pasta_audio)
            limpar_arquivo(caminho_arquivo_links)
            print(f"⬇️ Total de músicas baixadas: {total}")
            return total
        else:
            print("❌ Nenhum link encontrado ou link inválido.")
            return 0
    except Exception as e:
        print(f"❌ Erro ao processar o link: {e}")
        return -1
