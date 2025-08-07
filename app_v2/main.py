# main.py

import os
import sys

BASE = os.path.dirname(__file__)
for p in ("database","API","processamento","recomendacao","utils"):
    sys.path.append(os.path.join(BASE, p))

from processamento.processar_links   import processar_link
from processamento.extrator_fft       import processar_audio_local
from recomendacao.recomendar          import preparar_modelos_recomendacao
from database.db                      import criar_tabela

AUDIO_FOLDER = "/home/jovyan/work/audio"
LINKS_FILE   = "/home/jovyan/work/cache/links_youtube/links.txt"

def menu():
    print("\n🎵=== MusicData Pro ===🎵")
    print("1) Processar áudio local")
    print("2) Processar link do YouTube")
    print("3) Upload em massa (só banco)")
    print("4) Recalibrar & Recomendar")
    print("0) Sair")
    return input("Opção: ").strip()

def bulk_upload(pasta):
    print(f"[BULK] Iniciando upload em massa de: {pasta}")
    for f in os.listdir(pasta):
        if f.lower().endswith((".mp3",".wav")):
            caminho = os.path.join(pasta, f)
            # skip_recommend=True para não gerar recomendações
            processar_audio_local(caminho, skip_recommend=True)
    print("[BULK] Upload em massa concluído.")

def main():
    os.makedirs(AUDIO_FOLDER, exist_ok=True)
    os.makedirs(os.path.dirname(LINKS_FILE), exist_ok=True)

    criar_tabela()
    preparar_modelos_recomendacao()

    while True:
        opc = menu()
        if opc == "1":
            c = input("Caminho do arquivo: ").strip()
            processar_audio_local(c)
        elif opc == "2":
            link = input("Link YouTube: ").strip()
            fn, msg = processar_link(link, LINKS_FILE, AUDIO_FOLDER)
            print(msg)
            if fn:
                processar_audio_local(fn)
        elif opc == "3":
            pasta = input("Pasta para upload em massa: ").strip()
            bulk_upload(pasta)
        elif opc == "4":
            preparar_modelos_recomendacao(forcar_recalibragem=True)
            print("✅ Modelos recalibrados.")
        elif opc == "0":
            print("👋 Até mais!")
            break
        else:
            print("❌ Opção inválida.")

if __name__ == "__main__":
    main()
