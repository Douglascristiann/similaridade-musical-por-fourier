# main.py

import os
import sys

# Adiciona os diretórios da API e do processamento ao path
sys.path.append(os.path.join(os.path.dirname(__file__), "API"))
sys.path.append(os.path.join(os.path.dirname(__file__), "processamento"))
sys.path.append(os.path.join(os.path.dirname(__file__), "database"))
sys.path.append(os.path.join(os.path.dirname(__file__), "recomendacao"))

from processar_links import processar_link
from extrator_fft import processar_audio_local, processar_audio_youtube
from recomendar import preparar_modelos_recomendacao
from database.db import criar_tabela

# Caminhos fixos usados nos scripts
pasta_audio = "/home/jovyan/work/audio"
caminho_arquivo_links = "/home/jovyan/work/cache/links_youtube/links.txt"

def menu():
    print("\n=== Menu de Processamento de Áudio ===")
    print("1. Inserir arquivo de áudio local")
    print("2. Inserir link do YouTube")
    print("3. Gerar recomendações para todas as músicas (precisa ter 2 ou mais no DB)")
    print("0. Sair")
    return input("Escolha uma opção: ").strip()

def main():
    # Garante que as pastas existam
    os.makedirs(pasta_audio, exist_ok=True)
    os.makedirs(os.path.dirname(caminho_arquivo_links), exist_ok=True)

    # Cria a tabela no banco de dados se não existir
    criar_tabela()
    
    # Prepara os modelos de recomendação no início
    print("Preparando modelos de recomendação...")
    preparar_modelos_recomendacao()

    while True:
        opcao = menu()

        if opcao == "1":
            caminho = input("Digite o caminho do arquivo de áudio: ").strip()
            if os.path.isfile(caminho):
                try:
                    processar_audio_local(caminho)
                    print("✅ Arquivo processado com sucesso!")
                except Exception as e:
                    print(f"❌ Erro ao processar o áudio: {e}")
            else:
                print("❌ Caminho inválido ou arquivo inexistente.")

        elif opcao == "2":
            link = input("Digite o link do YouTube: ").strip()
            r = processar_link(link, caminho_arquivo_links, pasta_audio)
            print(f"{r}")
            
        elif opcao == "3":
            try:
                preparar_modelos_recomendacao(forcar_recalibragem=True)
            except Exception as e:
                print(f"❌ Erro ao recalibrar e gerar recomendações: {e}")

        elif opcao == "0":
            print("Encerrando...")
            break
        else:
            print("❌ Opção inválida. Tente novamente.")

if __name__ == "__main__":
    main()