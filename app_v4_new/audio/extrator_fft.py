# -*- coding: utf-8 -*-
"""
Extrai vetor fixo de 161 dims com HPSS, invariância de tom (chroma alinhado),
resumo estatístico (mean/std) e alguns descritores percussivos/ritmo.

Layout (total = 161):
- MFCC (18) mean+std base/delta/delta2 → 18*2*3 = 108
- Chroma (12) mean+std (harmônico, key-invariant) → 24  (132)
- Tonnetz (6) mean+std (harmônico) → 12                 (144)
- Spectral contrast (7) mean (harmônico) → 7            (151)
- Percussive (y_p): zcr mean+std (2), centroid mean (1), bandwidth mean (1),
  rolloff mean (1), flatness mean (1) → 6               (157)
- Ritmo: tempo global (1), var tempo (1), onset_strength mean (1),
         tempogram-centroid simples (1) → 4             (161)
"""
from __future__ import annotations
from typing import Dict, Tuple
import numpy as np
import librosa
import warnings

__all__ = ["extrair_features_completas", "get_feature_blocks"]

_HOP = 512
_NFFT = 2048

def _safe_tempo(y, sr):
    try:
        # Librosa >= 0.10
        from librosa.feature.rhythm import tempo as _tempo
        t = _tempo(y=y, sr=sr, hop_length=_HOP, aggregate=None)
        if t is None or len(t) == 0:
            return np.array([0.0])
        return t
    except Exception:
        # Compat < 0.10
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            t = librosa.beat.tempo(y=y, sr=sr, hop_length=_HOP, aggregate=None)
        if t is None or len(t) == 0:
            return np.array([0.0])
        return t

def _key_invariant_chroma(chroma: np.ndarray) -> np.ndarray:
    """Alinha chroma rotacionando para que o pico fique na posição 0 (tônica comum)."""
    if chroma.ndim != 2 or chroma.shape[0] != 12:
        return chroma
    mean = chroma.mean(axis=1)
    k = int(np.argmax(mean))
    return np.roll(chroma, -k, axis=0)

def _summ_stats(mat: np.ndarray, use_std: bool = True) -> np.ndarray:
    m = np.nanmean(mat, axis=1)
    if use_std:
        s = np.nanstd(mat, axis=1)
        return np.concatenate([m, s], axis=0)
    return m

def extrair_features_completas(y: np.ndarray, sr: int) -> np.ndarray:
    # normalização básica de loudness
    if np.max(np.abs(y)) > 1e-8:
        y = y / np.max(np.abs(y))

    # HPSS
    y_h, y_p = librosa.effects.hpss(y)

    # MFCC base/delta/delta2 (18)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=18, n_fft=_NFFT, hop_length=_HOP)
    d1   = librosa.feature.delta(mfcc, order=1)
    d2   = librosa.feature.delta(mfcc, order=2)
    mfcc_stats = np.concatenate([
        _summ_stats(mfcc, True),
        _summ_stats(d1,   True),
        _summ_stats(d2,   True)
    ], axis=0)  # 18*2*3 = 108

    # Chroma harmônico (key-invariant)
    chroma_h = librosa.feature.chroma_stft(y=y_h, sr=sr, n_fft=_NFFT, hop_length=_HOP)
    chroma_h = _key_invariant_chroma(chroma_h)
    chroma_stats = _summ_stats(chroma_h, True)  # 12*2 = 24

    # Tonnetz (harmônico)
    tonnetz = librosa.feature.tonnetz(y=y_h, sr=sr)
    tonnetz_stats = _summ_stats(tonnetz, True)  # 6*2 = 12

    # Spectral contrast (harmônico) — mean only
    spec_con = librosa.feature.spectral_contrast(y=y_h, sr=sr, n_fft=_NFFT, hop_length=_HOP)
    spec_con_mean = _summ_stats(spec_con, False)  # 7

    # Percussivo (y_p)
    zcr = librosa.feature.zero_crossing_rate(y=y_p, hop_length=_HOP)
    zcr_m, zcr_s = float(np.nanmean(zcr)), float(np.nanstd(zcr))
    cent = librosa.feature.spectral_centroid(y=y_p, sr=sr, n_fft=_NFFT, hop_length=_HOP)
    bw   = librosa.feature.spectral_bandwidth(y=y_p, sr=sr, n_fft=_NFFT, hop_length=_HOP)
    roll = librosa.feature.spectral_rolloff(y=y_p, sr=sr, n_fft=_NFFT, hop_length=_HOP)
    flat = librosa.feature.spectral_flatness(y=y_p, n_fft=_NFFT, hop_length=_HOP)
    percussive_stats = np.array([
        zcr_m, zcr_s,
        float(np.nanmean(cent)),
        float(np.nanmean(bw)),
        float(np.nanmean(roll)),
        float(np.nanmean(flat)),
    ], dtype=float)  # 6

    # Ritmo
    tempo_seq = _safe_tempo(y_p, sr)
    tempo_bpm = float(np.nanmedian(tempo_seq)) if tempo_seq.size else 0.0
    tempo_var = float(np.nanvar(tempo_seq))    if tempo_seq.size else 0.0
    onset_env = librosa.onset.onset_strength(y=y_p, sr=sr, hop_length=_HOP)
    onset_mean = float(np.nanmean(onset_env)) if onset_env.size else 0.0
    # tempogram “centro” simplificado
    try:
        tg = librosa.feature.tempogram(onset_envelope=onset_env, sr=sr, hop_length=_HOP)
        tg_centroid = float(np.nanmean(librosa.feature.spectral_centroid(S=tg)))
    except Exception:
        tg_centroid = 0.0
    ritmo = np.array([tempo_bpm, tempo_var, onset_mean, tg_centroid], dtype=float)  # 4

    # Concat final
    vec = np.concatenate([
        mfcc_stats,         # 108
        chroma_stats,       # 24  -> 132
        tonnetz_stats,      # 12  -> 144
        spec_con_mean,      # 7   -> 151
        percussive_stats,   # 6   -> 157
        ritmo               # 4   -> 161
    ], axis=0)

    assert vec.shape[0] == 161, f"Vetor final {vec.shape[0]} != 161"
    return vec.astype(float)

def get_feature_blocks() -> Dict[str, slice]:
    """
    Retorna os índices por bloco para padronização/ponderação:
    mfcc (0:108), chroma (108:132), tonnetz (132:144),
    spectral_contrast (144:151), percussive (151:157), tempo (157:161)
    """
    blocks = {
        "mfcc": slice(0, 108),
        "chroma": slice(108, 132),
        "tonnetz": slice(132, 144),
        "spectral_contrast": slice(144, 151),
        "percussive": slice(151, 157),
        "tempo": slice(157, 161)
    }
    return blocks
