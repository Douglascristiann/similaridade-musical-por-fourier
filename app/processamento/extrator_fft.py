import os
import numpy as np
import librosa
import matplotlib.pyplot as plt

def extrair_fft(audio_path):
    """
    Extrai o espectro de frequência usando FFT em um arquivo de áudio.
    Retorna as frequências e magnitudes.
    """
    y, sr = librosa.load(audio_path, sr=None)
    fft_result = np.fft.fft(y)
    freqs = np.fft.fftfreq(len(fft_result), 1/sr)
    magnitudes = np.abs(fft_result)
    metade = len(freqs) // 2
    return freqs[:metade], magnitudes[:metade]

def processar_pasta(caminho_pasta):
    """
    Lê todos os arquivos de áudio da pasta fornecida e extrai o espectro FFT de cada um.
    """
    extensoes_validas = ['.wav', '.mp3']
    for arquivo in os.listdir(caminho_pasta):
        if any(arquivo.endswith(ext) for ext in extensoes_validas):
            caminho_completo = os.path.join(caminho_pasta, arquivo)
            print(f"Processando: {arquivo}")
            try:
                freqs, mags = extrair_fft(caminho_completo)
                print(f" - Frequências extraídas: {len(freqs)} pontos")
                # Aqui depois vamos salvar no banco
            except Exception as e:
                print(f"Erro ao processar {arquivo}: {e}")

def plotar_fft_de_um(audio_path):
    freqs, magnitudes = extrair_fft(audio_path)
    plt.figure(figsize=(12, 5))
    plt.plot(freqs, magnitudes)
    plt.title(f"Espectro FFT de {os.path.basename(audio_path)}")
    plt.xlabel("Frequência (Hz)")
    plt.ylabel("Magnitude")
    plt.grid(True)
    plt.show()

# Execução direta
if __name__ == "__main__":
    pasta = r"C:\Users\silva\Documents\0_TCI\TCC\similaridade-musical-por-fourier\app\audio"
    processar_pasta(pasta)
