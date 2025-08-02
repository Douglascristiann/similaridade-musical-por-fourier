def gerar_spectrograma(y, sr, path_out, artista=None, titulo=None, modo='stft'):
    """
    Gera e salva um espectrograma logarítmico para o áudio.
    modo = 'stft' ou 'mel'
    """
    if y is None or sr is None:
        print(f"❌ Não foi possível gerar espectrograma para {path_out}, áudio inválido.")
        return

    # Garante que a pasta exista
    os.makedirs(os.path.dirname(path_out), exist_ok=True)

    plt.figure(figsize=(10, 4))

    if modo == 'mel':
        S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128)
        S_db = librosa.power_to_db(S, ref=np.max)
        librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='mel', cmap='magma')
    else:
        S = librosa.stft(y)
        S_db = librosa.amplitude_to_db(np.abs(S), ref=np.max)
        librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='log', cmap='magma')

    plt.colorbar(format='%+2.0f dB')
    plt.title(f"{titulo or 'Sem Título'} — {artista or 'Desconhecido'}", fontsize=12)
    plt.tight_layout()
    plt.savefig(path_out, dpi=120)
    plt.close()