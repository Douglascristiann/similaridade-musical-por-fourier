import os
import numpy as np
import librosa
import matplotlib.pyplot as plt
from scipy import signal
import librosa.display

def preprocess_audio(file_path, target_sr=22050, duration=None, normalize=True, noise_reduction=True):
    """
    Pré-processa um arquivo de áudio com normalização, filtro e remoção de silêncio.
    """
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
    """
    Extrai espectro de frequência usando FFT a partir do áudio pré-processado.
    """
    y, sr = preprocess_audio(audio_path)
    fft_result = np.fft.fft(y)
    freqs = np.fft.fftfreq(len(fft_result), 1/sr)
    magnitudes = np.abs(fft_result)
    metade = len(freqs) // 2
    return freqs[:metade], magnitudes[:metade], y, sr

def plotar_spectrograma(y, sr, titulo):
    """
    Plota o espectrograma do sinal de áudio.
    """
    plt.figure(figsize=(10, 4))
    S = librosa.stft(y)
    S_db = librosa.amplitude_to_db(np.abs(S), ref=np.max)
    librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='hz', cmap='magma')
    plt.colorbar(format="%+2.0f dB")
    plt.title(f"Spectrograma: {titulo}")
    plt.tight_layout()
    plt.show()

def processar_pasta(caminho_pasta):
    """
    Processa todos os arquivos de áudio da pasta fornecida.
    """
    extensoes_validas = ['.wav', '.mp3']
    for arquivo in os.listdir(caminho_pasta):
        if any(arquivo.endswith(ext) for ext in extensoes_validas):
            caminho_completo = os.path.join(caminho_pasta, arquivo)
            print(f"\nProcessando: {arquivo}")
            try:
                freqs, mags, y, sr = extrair_fft(caminho_completo)
                print(f" - FFT extraído: {len(freqs)} pontos")
                plotar_spectrograma(y, sr, arquivo)
                # Aqui você pode salvar os dados no banco de dados posteriormente
            except Exception as e:
                print(f"Erro ao processar {arquivo}: {e}")

# Execução principal
if __name__ == "__main__":
    username = os.environ.get("USERNAME")
    pasta = fr"C:\Users\{username}\Documents\GitHub\similaridade-musical-por-fourier\app\audio"
    if not os.path.exists(pasta):
        print(f"❌ Caminho não encontrado: {pasta}")
    else:
        processar_pasta(pasta)
