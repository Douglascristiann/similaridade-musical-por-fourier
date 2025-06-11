#!/usr/bin/env python3
import sys
import os

# Caminho absoluto para o diretório 'processamento'
extrator_fft_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'processamento'))

# Adiciona o diretório ao sys.path se ainda não estiver lá
if extrator_fft_path not in sys.path:
    sys.path.append(extrator_fft_path)

try:
    from extrator_fft import executar
except ModuleNotFoundError as e:
    print(f"❌ Erro ao importar o módulo 'extrator_fft': {e}")
    print("💡 Verifique se o arquivo 'extrator_fft.py' existe dentro da pasta 'processamento'.")
    sys.exit(1)  # Encerra o programa com erro


