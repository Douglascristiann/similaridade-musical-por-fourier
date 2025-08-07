# API/reconhecimento_metadado.py

from tinytag import TinyTag

def reconhecer_metadado(path):
    try:
        tag = TinyTag.get(path)
        return (
            tag.artist or "Não Encontrado",
            tag.title  or "Não Encontrado",
            tag.album  or "Não Encontrado",
            tag.genre  or "Não Encontrado",
            "Não Encontrado"
        )
    except:
        return ("Não Encontrado",)*5
