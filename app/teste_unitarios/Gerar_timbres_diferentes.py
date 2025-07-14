from scipy.io.wavfile import write
import numpy as np
import os

# Diretório de saída para os testes
output_dir = "/home/jovyan/work/audio/timbres_diferentes"
os.makedirs(output_dir, exist_ok=True)

# Parâmetros comuns
duration = 2.0  # segundos
sr = 22050  # taxa de amostragem
t = np.linspace(0, duration, int(sr * duration), endpoint=False)
frequency = 261.63  # C4

# 2º TESTE: Mesma nota (C4) com diferentes timbres simulados por envelope simples
def generate_timbre_wave(timbre_type):
    if timbre_type == "seno":
        return 0.5 * np.sin(2 * np.pi * frequency * t)
    elif timbre_type == "quadrada":
        return 0.5 * np.sign(np.sin(2 * np.pi * frequency * t))
    elif timbre_type == "triangular":
        return 0.5 * 2 * np.abs(2 * (t * frequency - np.floor(t * frequency + 0.5))) - 1
    elif timbre_type == "dente_de_serra":
        return 0.5 * 2 * (t * frequency - np.floor(t * frequency))
    else:
        raise ValueError("Timbre não suportado")

# Lista de timbres a serem testados
timbres = ["seno", "quadrada", "triangular", "dente_de_serra"]
file_paths = []

for timbre in timbres:
    y = generate_timbre_wave(timbre)
    y_int16 = np.int16(y / np.max(np.abs(y)) * 32767)
    file_path = os.path.join(output_dir, f"C4_{timbre}.wav")
    write(file_path, sr, y_int16)
    file_paths.append(file_path)

file_paths