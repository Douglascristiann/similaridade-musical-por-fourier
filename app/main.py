#!/usr/bin/env python3
import sys
import os

def main():
    # Caminho absoluto para o diretório 'teste_unitarios'
    teste_unitarios_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'teste_unitarios'))
    
    # Adiciona ao sys.path se ainda não estiver presente
    if teste_unitarios_path not in sys.path:
        sys.path.append(teste_unitarios_path)

    try:
        # Importa a função do arquivo preprocess_return.py
        from preprocess_return import executar_testes

        print("✅ Executando testes do módulo preprocess_return...")
        executar_testes()
    except ModuleNotFoundError as e:
        print(f"❌ Erro ao importar o módulo 'preprocess_return': {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
