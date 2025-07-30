import os
import sys

# Adiciona o diretório 'processamento' ao path
sys.path.append(os.path.join(os.path.dirname(__file__), "processamento"))
sys.path.append(os.path.join(os.path.dirname(__file__), "API"))

from extrator_fft import processar_audio_local, processar_audio_youtube

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
            try:
                processar_audio_youtube(link)
                print("✅ Link processado com sucesso!")
            except Exception as e:
                print(f"❌ Erro ao processar o link: {e}")

        elif opcao == "0":
            print("Encerrando...")
            break
        else:
            print("❌ Opção inválida. Tente novamente.")

if __name__ == "__main__":
    main()
