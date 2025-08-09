
from __future__ import annotations
import numpy as np
import librosa

from .feature_schema import stack_features, assert_against_schema

HOP_LENGTH = 512
N_MFCC = 40

def _normalize_simple_rms(y: np.ndarray, target_rms: float = 0.1) -> np.ndarray:
    cur = float(np.sqrt(np.mean(np.square(y)))) if y.size else 0.0
    if cur < 1e-12:
        return y
    y = y * (target_rms / cur)
    return np.clip(y, -1.0, 1.0)

def normalize_loudness(y: np.ndarray, sr: int, target_lufs: float = -23.0) -> np.ndarray:
    try:
        import pyloudnorm as pyln  # optional
        meter = pyln.Meter(sr)
        loudness = meter.integrated_loudness(y.astype(float))
        y = pyln.normalize.loudness(y.astype(float), loudness, target_lufs).astype(np.float32)
        return np.clip(y, -1.0, 1.0)
    except Exception:
        return _normalize_simple_rms(y)

def _beat_sync(F: np.ndarray, beat_frames: np.ndarray | list[int]) -> np.ndarray:
    if F.ndim == 1:
        F = F[np.newaxis, :]
    if beat_frames is None or len(beat_frames) < 2:
        return np.median(F, axis=1, keepdims=True)
    beat_frames = librosa.util.fix_frames(np.asarray(beat_frames), x_min=0, x_max=F.shape[1]-1)
    Fs = librosa.util.sync(F, beat_frames, aggregate=np.median)
    if Fs.size == 0:
        return np.median(F, axis=1, keepdims=True)
    return Fs

def _rotate_chroma_to_c(C: np.ndarray) -> tuple[np.ndarray, int]:
    if C.shape[0] != 12:
        raise ValueError("Chroma must have 12 bands (12 x T).")
    prof = C.sum(axis=1)
    shift = int(np.argmax(prof)) if prof.size else 0
    return np.roll(C, -shift, axis=0), shift

def _tiv6_from_chroma(C: np.ndarray) -> np.ndarray:
    if C.shape[0] != 12:
        raise ValueError("Chroma must have 12 bands (12 x T).")
    X = np.fft.rfft(C, n=12, axis=0)  # -> (7 x T), indices 0..6
    TIV = np.abs(X[1:7, :])           # k=1..6
    tiv6 = np.mean(TIV, axis=1)       # 6D
    return tiv6.astype(np.float32)

def extrair_features_completas(y: np.ndarray, sr: int) -> np.ndarray:
    # mono float32
    if y.ndim > 1:
        y = np.mean(y, axis=0)
    y = y.astype(np.float32, copy=False)
    y = normalize_loudness(y, sr)

    try:
        y_h, y_p = librosa.effects.hpss(y)
    except Exception:
        y_h = librosa.effects.harmonic(y)
        y_p = y - y_h

    tempo_framewise = librosa.beat.tempo(y=y_p, sr=sr, hop_length=HOP_LENGTH, aggregate=None)
    tempo_bpm = float(np.median(tempo_framewise)) if tempo_framewise.size else float(
        librosa.beat.tempo(y=y_p, sr=sr, hop_length=HOP_LENGTH)
    )
    tempo_var = float(np.std(tempo_framewise)) if tempo_framewise.size else 0.0
    _, beat_frames = librosa.beat.beat_track(y=y_p, sr=sr, hop_length=HOP_LENGTH)

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=N_MFCC, hop_length=HOP_LENGTH)
    d1 = librosa.feature.delta(mfcc)
    d2 = librosa.feature.delta(mfcc, order=2)
    mfcc_mean    = _beat_sync(mfcc, beat_frames).mean(axis=1)
    mfcc_d1_mean = _beat_sync(d1,   beat_frames).mean(axis=1)
    mfcc_d2_mean = _beat_sync(d2,   beat_frames).mean(axis=1)

    contrast = librosa.feature.spectral_contrast(y=y, sr=sr, hop_length=HOP_LENGTH)
    contrast_mean = _beat_sync(contrast, beat_frames).mean(axis=1)  # 7D

    chroma_h = librosa.feature.chroma_cqt(y=y_h, sr=sr, hop_length=HOP_LENGTH)
    chroma_h_sync = _beat_sync(chroma_h, beat_frames)               # 12 x Nb
    chroma_ci, _ = _rotate_chroma_to_c(chroma_h_sync)               # align to C
    chroma_ci_mean = chroma_ci.mean(axis=1)                         # 12D

    tonnetz_h = librosa.feature.tonnetz(y=y_h, sr=sr)
    tonnetz_h_mean = _beat_sync(tonnetz_h, beat_frames).mean(axis=1)  # 6D

    tiv6 = _tiv6_from_chroma(chroma_h_sync)                         # 6D

    zcr = librosa.feature.zero_crossing_rate(y=y_p, hop_length=HOP_LENGTH)
    zcr_mean = _beat_sync(zcr, beat_frames).mean(axis=1)            # 1D

    centroid = librosa.feature.spectral_centroid(y=y_p, sr=sr, hop_length=HOP_LENGTH)
    centroid_mean = _beat_sync(centroid, beat_frames).mean(axis=1)  # 1D

    bandwidth = librosa.feature.spectral_bandwidth(y=y_p, sr=sr, hop_length=HOP_LENGTH)
    bandwidth_mean = _beat_sync(bandwidth, beat_frames).mean(axis=1)# 1D

    rolloff = librosa.feature.spectral_rolloff(y=y_p, sr=sr, hop_length=HOP_LENGTH)
    rolloff_mean = _beat_sync(rolloff, beat_frames).mean(axis=1)    # 1D

    blocks = {
        "mfcc": mfcc_mean.astype(np.float32),
        "mfcc_delta": mfcc_d1_mean.astype(np.float32),
        "mfcc_delta2": mfcc_d2_mean.astype(np.float32),
        "spectral_contrast": contrast_mean.astype(np.float32),
        "chroma_h_ci": chroma_ci_mean.astype(np.float32),
        "tiv6": tiv6.astype(np.float32),
        "tonnetz_h": tonnetz_h_mean.astype(np.float32),
        "zcr_p": zcr_mean.astype(np.float32),
        "centroid_p": centroid_mean.astype(np.float32),
        "bandwidth_p": bandwidth_mean.astype(np.float32),
        "rolloff_p": rolloff_mean.astype(np.float32),
        "tempo_bpm": np.array([tempo_bpm], dtype=np.float32),
        "tempo_var": np.array([tempo_var], dtype=np.float32),
    }

    vec, lens = stack_features(blocks)
    if not np.all(np.isfinite(vec)):
        raise ValueError("NaN/Inf found in feature vector.")
    assert_against_schema(vec.size, lens)
    return vec.astype(np.float32)
