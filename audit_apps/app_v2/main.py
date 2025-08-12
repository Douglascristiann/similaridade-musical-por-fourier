import os
import sys
import logging

from processamento.processar_links import processar_link, processar_playlist
from processamento.extrator_fft   import processar_audio_local
from recomendacao.recomendar       import preparar_modelos_recomendacao
from database.db                   import criar_tabela
from config                        import AUDIO_FOLDER

logging.basicConfig(level=logging.INFO)

AUDIO_FOLDER = AUDIO_FOLDER
LINKS_FILE   = "/home/jovyan/work/cache/links_youtube/links.txt"

def menu():
    print("\n🎵=== MusicData Pro ===🎵")
    print("1) Processar áudio local")
    print("2) Processar link do YouTube")
    print("3) Upload em massa (pasta local)")
    print("4) Recalibrar & Recomendar")
    print("5) Playlist do YouTube (bulk)")
    print("0) Sair")
    return input("Opção: ").strip()

def bulk_local(pasta):
    logging.info(f"[BULK] Pasta local: {pasta}")
    for f in os.listdir(pasta):
        if f.lower().endswith((".mp3",".wav")):
            processar_audio_local(os.path.join(pasta, f),
                                  skip_recommend=True,
                                  skip_db_check=True)
    logging.info("[BULK] Concluído.")

def bulk_playlist(link):
    logging.info(f"[BULK] Playlist: {link}")
    arquivos, msg = processar_playlist(link, LINKS_FILE, AUDIO_FOLDER)
    print(msg)
    for fn in arquivos:
        processar_audio_local(fn, skip_recommend=True, skip_db_check=True)
    logging.info("[BULK] Playlist processada.")

def main():
    os.makedirs(AUDIO_FOLDER, exist_ok=True)
    os.makedirs(os.path.dirname(LINKS_FILE), exist_ok=True)
    criar_tabela()
    preparar_modelos_recomendacao()

    while True:
        opc = menu()
        if opc == "1":
            c = input("Arquivo: ").strip()
            processar_audio_local(c)
        elif opc == "2":
            link = input("Link YouTube: ").strip()
            fn, msg = processar_link(link, LINKS_FILE, AUDIO_FOLDER)
            print(msg)
            if fn:
                processar_audio_local(fn)
        elif opc == "3":
            pasta = input("Pasta local: ").strip()
            bulk_local(pasta)
        elif opc == "4":
            preparar_modelos_recomendacao(forcar_recalibragem=True)
            print("✅ Modelos recalibrados.")
        elif opc == "5":
            link = input("Link da playlist/álbum: ").strip()
            bulk_playlist(link)
        elif opc == "0":
            break
        else:
            print("❌ Opção inválida.")

if __name__ == "__main__":
    main()
