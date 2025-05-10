import os
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
from scipy import signal
from scipy.spatial.distance import euclidean

def preprocess_audio(file_path, target_sr=22050, duration=None, normalize=True, noise_reduction=True):
    audio, sr = librosa.load(file_path, sr=target_sr, duration=duration, mono=True)

    if normalize:
        audio = librosa.util.normalize(audio)

    if noise_reduction:
        lowcut = 80
        highcut = 10000
        nyquist = 0.5 * sr
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = signal.butter(4, [low, high], btype='band')
        audio = signal.filtfilt(b, a, audio)

    audio, _ = librosa.effects.trim(audio, top_db=20)
    return audio, sr

def extrair_fft(audio_path):
    y, sr = preprocess_audio(audio_path)
    fft_result = np.fft.fft(y)
    freqs = np.fft.fftfreq(len(fft_result), 1 / sr)
    magnitudes = np.abs(fft_result)
    metade = len(freqs) // 2
    return freqs[:metade], magnitudes[:metade], y, sr

def extrair_caracteristicas(audio_path, n_frequencias=20):
    freqs, mags, _, _ = extrair_fft(audio_path)
    indices_top = np.argsort(mags)[-n_frequencias:]
    caracteristicas = freqs[indices_top]
    return np.sort(caracteristicas)

def plotar_spectrograma(y, sr, titulo):
    plt.figure(figsize=(10, 4))
    S = librosa.stft(y)
    S_db = librosa.amplitude_to_db(np.abs(S), ref=np.max)
    librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='hz', cmap='magma')
    plt.colorbar(format="%+2.0f dB")
    plt.title(f"Spectrograma: {titulo}")
    plt.tight_layout()
    plt.show()

def comparar_musicas(vetor1, vetor2):
    return euclidean(vetor1, vetor2)

def recomendar_musicas(pasta):
    musicas = {}
    print("\n🎼 Extraindo características das músicas...\n")
    for arquivo in os.listdir(pasta):
        if arquivo.endswith(('.mp3', '.wav')):
            caminho = os.path.join(pasta, arquivo)
            print(f"🎵 Processando {arquivo}")
            musicas[arquivo] = extrair_caracteristicas(caminho)

    print("\n📊 Gerando recomendações baseadas em similaridade de frequência...\n")
    for base in musicas:
        distancias = []
        for outra in musicas:
            if base != outra:
                d = comparar_musicas(musicas[base], musicas[outra])
                distancias.append((outra, d))
        distancias.sort(key=lambda x: x[1])
        if distancias:
            recomendado = distancias[0][0]
            print(f"✅ Recomendação para '{base}': '{recomendado}' (distância: {distancias[0][1]:.2f})")

def processar_completo(pasta):
    for arquivo in os.listdir(pasta):
        if arquivo.endswith(('.mp3', '.wav')):
            caminho = os.path.join(pasta, arquivo)
            print(f"\n🎧 Plotando espectrograma de: {arquivo}")
            try:
                _, _, y, sr = extrair_fft(caminho)
                plotar_spectrograma(y, sr, arquivo)
            except Exception as e:
                print(f"Erro: {e}")

# Execução principal
if __name__ == "__main__":
    username = os.environ.get("USERNAME") or os.getlogin()
    pasta = fr"C:\Users\{username}\Documents\GitHub\similaridade-musical-por-fourier\app\audio"
    
    if not os.path.exists(pasta):
        print(f"❌ Caminho não encontrado: {pasta}")
    else:
        processar_completo(pasta)
        recomendar_musicas(pasta)

