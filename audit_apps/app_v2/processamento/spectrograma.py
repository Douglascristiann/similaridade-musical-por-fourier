# processamento/spectrograma.py

import os
import numpy as np
import matplotlib.pyplot as plt
import librosa
import librosa.display

def gerar_spectrograma(y, sr, path_out, artista=None, titulo=None, modo='stft'):
    print(f"[SPEC] Gerando spectrograma em {path_out}")
    os.makedirs(os.path.dirname(path_out), exist_ok=True)
    plt.figure(figsize=(10, 4))

    if modo == 'mel':
        S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128)
        S_db = librosa.power_to_db(S, ref=np.max)
        librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='mel')
    else:
        S = librosa.stft(y)
        S_db = librosa.amplitude_to_db(np.abs(S), ref=np.max)
        librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='log')

    plt.colorbar(format='%+2.0f dB')
    plt.title(f"{titulo or '—'} — {artista or '—'}")
    plt.tight_layout()
    plt.savefig(path_out, dpi=120)
    plt.close()
    print("[SPEC] Spectrograma salvo.")
