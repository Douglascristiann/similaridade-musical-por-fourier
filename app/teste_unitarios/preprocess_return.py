import os
import numpy as np
import librosa
import soundfile as sf

# Carrega o áudio original
input_path = "entrada/004.mp3"
y, sr = librosa.load(input_path, sr=None)

# Processamento do áudio (sua limpeza, filtros etc)

# Caminho de saída com nome do arquivo e extensão .wav
output_dir = r"C:\Users\douglas.cunha\Documents\GitHub\similaridade-musical-por-fourier\app\teste_unitarios\audio_PosProcessado"
os.makedirs(output_dir, exist_ok=True)  # Cria a pasta se não existir

output_path = os.path.join(output_dir, "004_pos_processado.wav")

# Salva como WAV
sf.write(output_path, y, sr)
