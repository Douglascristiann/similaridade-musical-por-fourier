# main.py

import os
import sys

# Adiciona os diretórios da API e do processamento ao path
sys.path.append(os.path.join(os.path.dirname(__file__), "API"))
sys.path.append(os.path.join(os.path.dirname(__file__), "processamento"))

from processar_links import processar_link
from extrator_fft import processar_audio_local, processar_pasta

# Caminhos fixos usados nos scripts
pasta_audio = "/home/jovyan/work/audio"
caminho_arquivo_links = "/home/jovyan/work/cache/links_youtube/links.txt"

def menu():
    print("\n=== Menu de Processamento de Áudio ===")
    print("1. Inserir arquivo de áudio local")
    print("2. Inserir link do YouTube")
    print("0. Sair")
    return input("Escolha uma opção: ").strip()

def main():
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
            metadados = processar_link(link, caminho_arquivo_links, pasta_audio)

            if metadados:
                processar_pasta(pasta_audio, metadados)
            elif metadados == {} or metadados == []:
                print("Aqui será realizada a recomendação de músicas.")
            else:
                print("❌ Erro ao processar o link.")
            
        elif opcao == "0":
            print("Encerrando...")
            break
        else:
            print("❌ Opção inválida. Tente novamente.")

if __name__ == "__main__":
    main()
