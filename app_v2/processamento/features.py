# processamento/features.py

import numpy as np
import librosa
from librosa.feature.rhythm import tempo
from config import EXPECTED_FEATURE_LENGTH

def preprocess_audio(path, sr=22050):
    print(f"[FEAT] Carregando e normalizando: {path}")
    try:
        y, _ = librosa.load(path, sr=sr, mono=True)
        y = librosa.util.normalize(y)
        y, _ = librosa.effects.trim(y, top_db=20)
        if len(y) < sr * 0.1:
            print(f"[FEAT] ⚠️ Áudio muito curto ({len(y)/sr:.2f}s).")
            return None, None
        print("[FEAT] Pré-processamento concluído.")
        return y, sr
    except Exception as e:
        print(f"[FEAT] ❌ Erro no pré-processamento: {e}")
        return None, None

def extrair_features_completas(y, sr):
    print("[FEAT] Iniciando extração de features…")
    if y is None or sr is None or len(y) < sr * 0.2:
        print("[FEAT] Áudio inválido para extração. Retornando zeros.")
        return np.zeros(EXPECTED_FEATURE_LENGTH)

    try:
        # MFCCs
        mfcc        = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=40)
        mfcc_mean   = np.mean(mfcc, axis=1)
        mfcc_delta  = librosa.feature.delta(mfcc)
        mfcc_delta_mean  = np.mean(mfcc_delta, axis=1)
        mfcc_delta2 = librosa.feature.delta(mfcc, order=2)
        mfcc_delta2_mean = np.mean(mfcc_delta2, axis=1)

        # Chroma, Tonnetz, Contrast
        chroma_vals  = librosa.feature.chroma_stft(y=y, sr=sr)
        chroma_mean  = np.mean(chroma_vals, axis=1)
        tonnetz_vals = librosa.feature.tonnetz(y=librosa.effects.harmonic(y), sr=sr)
        tonnetz_mean = np.mean(tonnetz_vals, axis=1)
        contrast_vals = librosa.feature.spectral_contrast(y=y, sr=sr, n_bands=6)
        contrast_mean = np.mean(contrast_vals, axis=1)

        # Atributos escalares (mean)
        tempo_arr    = tempo(y=y, sr=sr)
        tempo_mean   = float(tempo_arr[0]) if hasattr(tempo_arr, "__len__") else float(tempo_arr)
        rms_vals     = librosa.feature.rms(y=y);       rms_mean   = float(np.mean(rms_vals))
        zcr_vals     = librosa.feature.zero_crossing_rate(y); zcr_mean = float(np.mean(zcr_vals))
        rolloff_vals = librosa.feature.spectral_rolloff(y=y, sr=sr); rolloff_mean = float(np.mean(rolloff_vals))
        bw_vals      = librosa.feature.spectral_bandwidth(y=y, sr=sr); bandwidth_mean = float(np.mean(bw_vals))

        # Extras (mean/std)
        centroid_vals = librosa.feature.spectral_centroid(y=y, sr=sr)
        centroid_mean = float(np.mean(centroid_vals)); centroid_std = float(np.std(centroid_vals))
        flat_vals     = librosa.feature.spectral_flatness(y=y)
        flat_mean     = float(np.mean(flat_vals));     flat_std     = float(np.std(flat_vals))
        contrast_std  = float(np.mean(np.std(contrast_vals, axis=1)))
        chroma_std    = float(np.mean(np.std(chroma_vals, axis=1)))
        tonnetz_std   = float(np.mean(np.std(tonnetz_vals, axis=1)))
        rms_std       = float(np.std(rms_vals));      zcr_std      = float(np.std(zcr_vals))
        rolloff_std   = float(np.std(rolloff_vals));  bandwidth_std= float(np.std(bw_vals))

        # Concatenação final
        features = np.concatenate([
            mfcc_mean,
            mfcc_delta_mean,
            mfcc_delta2_mean,
            chroma_mean,
            tonnetz_mean,
            contrast_mean,
            [tempo_mean, rms_mean, zcr_mean, rolloff_mean, bandwidth_mean,
             centroid_mean, centroid_std, flat_mean, flat_std,
             contrast_std, chroma_std, tonnetz_std, rms_std, zcr_std,
             rolloff_std, bandwidth_std]
        ])

        print(f"[FEAT] Extraídas {features.shape[0]} features antes do pad.")
        # Padding, se necessário
        if features.shape[0] < EXPECTED_FEATURE_LENGTH:
            pad = EXPECTED_FEATURE_LENGTH - features.shape[0]
            print(f"[FEAT] Aplicando pad: {features.shape[0]} → {EXPECTED_FEATURE_LENGTH}")
            features = np.pad(features, (0, pad))

        print("[FEAT] Extração completa.")
        return features

    except Exception as e:
        print(f"[FEAT] ❌ Erro ao extrair features: {e}")
        return np.zeros(EXPECTED_FEATURE_LENGTH)
