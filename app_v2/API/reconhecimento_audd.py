# API/reconhecimento_audd.py

import requests
from config import AUDD_TOKEN

def reconhecer_audd(path):
    try:
        with open(path, "rb") as f:
            data = {"api_token": AUDD_TOKEN, "return":"apple_music,spotify"}
            r = requests.post("https://api.audd.io/", data=data, files={"file":f}, timeout=10).json()
        res = r.get("result")
        if res:
            return (
                res.get("artist","Não Encontrado"),
                res.get("title","Não Encontrado"),
                res.get("album","Não Encontrado"),
                res.get("genre","Não Encontrado"),
                "Não Encontrado"
            )
    except Exception as e:
        print("❌ AudD:", e)
    return ("Não Encontrado",)*5
