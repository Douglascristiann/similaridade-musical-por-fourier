#!/usr/bin/env python3
import sys
import os

# Adiciona o diretório 'processamento' ao path
caminho_superior = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'processamento'))
if caminho_superior not in sys.path:
    sys.path.append(caminho_superior)

from extrator_fft import executar

def main():
    print("🎶 Bem-vindo ao sistema de recomendação musical baseado em FFT 🎶")
    resposta = input("Deseja iniciar o sistema de recomendação? [s/n]: ").strip().lower()

    if resposta == 's':
        print("\n🔄 Iniciando processamento...\n")
        executar()
    else:
        print("❌ Execução cancelada pelo usuário.")

if __name__ == "__main__":
    main()


