import numpy as np
from scipy.io.wavfile import write
import os

# Parâmetros de áudio
sr = 22050  # taxa de amostragem
duracao = 2.0  # duração em segundos

# Frequências de notas musicais (escala temperada)
notas_freqs = {
    "C4": 261.63,
    "D4": 293.66,
    "E4": 329.63,
    "F4": 349.23,
    "G4": 392.00,
    "A4": 440.00,
    "B4": 493.88,
    "C5": 523.25,
}

# Pasta de saída
pasta_saida = "/home/jovyan/work/audio/notas_limpas"
os.makedirs(pasta_saida, exist_ok=True)

# Função para gerar senoide e salvar como WAV
def gerar_senoide(freq, nome_arquivo):
    t = np.linspace(0, duracao, int(sr * duracao), endpoint=False)
    onda = 0.5 * np.sin(2 * np.pi * freq * t)
    onda_pcm = np.int16(onda * 32767)
    write(nome_arquivo, sr, onda_pcm)

# Gerar arquivos de áudio para cada nota
arquivos_gerados = []
for nome_nota, freq in notas_freqs.items():
    caminho = os.path.join(pasta_saida, f"{nome_nota}.wav")
    gerar_senoide(freq, caminho)
    arquivos_gerados.append(caminho)

arquivos_gerados

#### Valores esperados:
#C4 ≈ C5: alta similaridade (~90%+)

#C4 ≈ D4: moderada (~70–85%)

#C4 ≈ G4: baixa (~50–70%)

#C4 ≈ ruído aleatório: muito baixa (~<40%)