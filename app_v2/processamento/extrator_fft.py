# processamento/extrator_fft.py

import os
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
from config import EXPECTED_FEATURE_LENGTH, PASTA_SPECTROGRAMAS
from database.db import inserir_musica
from API.reconhecimento import reconhecer_musica
from API.processar_links import buscar_youtube_link
import asyncio

# =================== EXTRAÇÃO DE FEATURES ===================
def preprocess_audio(path, sr=22050):
    """Carrega e pré-processa um arquivo de áudio (normaliza e remove silêncios)."""
    try:
        y, _ = librosa.load(path, sr=sr, mono=True)
        y = librosa.util.normalize(y)
        y, _ = librosa.effects.trim(y, top_db=20)
        if len(y) < sr * 0.1:
            print(f"⚠️ Áudio muito curto após trim: {path}. Pode causar problemas na extração de features.")
            return None, None
        return y, sr
    except Exception as e:
        print(f"❌ Erro ao pré-processar áudio {path}: {e}")
        return None, None

def extrair_features_completas(y, sr):
    """
    Extrai um conjunto completo de características de áudio.
    """
    if y is None or sr is None or len(y) < sr * 0.2:
        return np.zeros(EXPECTED_FEATURE_LENGTH)

    try:
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
        mfcc_delta = librosa.feature.delta(mfcc)
        mfcc_delta2 = librosa.feature.delta(mfcc, order=2)

        mfcc_mean = np.mean(mfcc, axis=1)
        mfcc_delta_mean = np.mean(mfcc_delta, axis=1)
        mfcc_delta2_mean = np.mean(mfcc_delta2, axis=1)

        chroma = np.mean(librosa.feature.chroma_stft(y=y, sr=sr), axis=1)
        tonnetz = np.mean(librosa.feature.tonnetz(y=librosa.effects.harmonic(y), sr=sr), axis=1)
        contrast = np.mean(librosa.feature.spectral_contrast(y=y, sr=sr), axis=1)
        
        try:
            tempo_val = librosa.beat.tempo(y=y, sr=sr)[0]
        except Exception as e:
            tempo_val = 0.0

        rms = np.mean(librosa.feature.rms(y=y))
        zcr = np.mean(librosa.feature.zero_crossing_rate(y))
        rolloff = np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr))
        bandwidth = np.mean(librosa.feature.spectral_bandwidth(y=y, sr=sr))

        features = [
            mfcc_mean, mfcc_delta_mean, mfcc_delta2_mean,
            chroma, tonnetz, contrast,
            [tempo_val], [rms], [zcr], [rolloff], [bandwidth]
        ]
        final_features = np.concatenate(features)

        if len(final_features) != EXPECTED_FEATURE_LENGTH:
            print(f"⚠️ Ajustando vetor de features: {len(final_features)} → {EXPECTED_FEATURE_LENGTH}")
            final_features = np.pad(final_features, (0, max(0, EXPECTED_FEATURE_LENGTH - len(final_features))))[:EXPECTED_FEATURE_LENGTH]

        return final_features

    except Exception as e:
        print(f"❌ Erro ao extrair features completas: {e}")
        return np.zeros(EXPECTED_FEATURE_LENGTH)

def gerar_spectrograma(y, sr, path_out, artista=None, titulo=None, modo='stft'):
    """
    Gera e salva um espectrograma logarítmico para o áudio.
    """
    if y is None or sr is None:
        print(f"❌ Não foi possível gerar espectrograma para {path_out}, áudio inválido.")
        return

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


def processar_audio_local(caminho):
    """Processa um arquivo de áudio local, extraindo metadados, features e salvando no banco."""
    print(f"🎵 Processando arquivo local: {caminho}")

    # Reconhecimento e busca de link do youtube
    artista, titulo, album, genero, capa_album = asyncio.run(reconhecer_musica(caminho))
    link_youtube = buscar_youtube_link(artista, titulo)
    
    # Extração de features e geração de espectrograma
    y, sr = preprocess_audio(caminho)
    if y is None:
        return
        
    features = extrair_features_completas(y, sr)
    
    nome_arquivo = os.path.splitext(os.path.basename(caminho))[0]
    spectro_path = os.path.join(PASTA_SPECTROGRAMAS, f"{nome_arquivo}_spectrograma.png")
    gerar_spectrograma(y, sr, spectro_path, artista, titulo)
    print(f"📸 Espectrograma salvo em: {spectro_path}")

    # Inserção no banco
    if len(features) == EXPECTED_FEATURE_LENGTH:
        inserir_musica(nome_arquivo, features, artista, titulo, album, genero, capa_album, link_youtube)
    else:
        print(f"❌ Vetor de características inconsistente ({len(features)}), não será inserido no banco.")
    
def processar_audio_youtube(caminho_arquivo_local):
    """
    Função de conveniência que apenas chama o processador de áudio local.
    É usada no `main.py` após o download do YouTube.
    """
    processar_audio_local(caminho_arquivo_local)