import os
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
from scipy import signal
from scipy.spatial.distance import euclidean
import mysql.connector

# Configurações do banco
USER = "root"
PASSWORD = "managerffti8p68"
DB = "dbmusicadata"
HOST = "db"
PORT = 3306

# ---------- FUNÇÕES DE BANCO DE DADOS ------------------

def criar_tabela():
    try:
        conn = mysql.connector.connect(user=USER, password=PASSWORD, host=HOST, port=PORT, database=DB)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tb_musicas (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nome VARCHAR(255) NOT NULL UNIQUE,
                caminho TEXT,
                frequencias TEXT NOT NULL,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("📦 Tabela verificada/criada com sucesso.")
    except Exception as e:
        print(f"❌ Erro ao criar tabela: {e}")

def musica_existe(nome):
    try:
        conn = mysql.connector.connect(user=USER, password=PASSWORD, host=HOST, port=PORT, database=DB)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tb_musicas WHERE nome = %s", (nome,))
        resultado = cur.fetchone()[0]
        cur.close()
        conn.close()
        return resultado > 0
    except Exception as e:
        print(f"❌ Erro ao verificar existência: {e}")
        return False

def inserir_musica_banco(nome, caminho, frequencias):
    try:
        if musica_existe(nome):
            print(f"⚠️ Música '{nome}' já está cadastrada. Pulando.")
            return
        conn = mysql.connector.connect(user=USER, password=PASSWORD, host=HOST, port=PORT, database=DB)
        cur = conn.cursor()
        freq_str = ",".join(map(str, frequencias))
        cur.execute("""
            INSERT INTO tb_musicas (nome, caminho, frequencias)
            VALUES (%s, %s, %s)
        """, (nome, caminho, freq_str))
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ Música '{nome}' inserida com sucesso.")
    except Exception as e:
        print(f"❌ Erro ao inserir no banco: {e}")

def carregar_musicas_do_banco():
    try:
        conn = mysql.connector.connect(user=USER, password=PASSWORD, host=HOST, port=PORT, database=DB)
        cur = conn.cursor()
        cur.execute("SELECT nome, frequencias FROM tb_musicas")
        dados = cur.fetchall()
        cur.close()
        conn.close()
        musicas = {}
        for nome, freq_str in dados:
            freqs = list(map(float, freq_str.split(",")))
            musicas[nome] = freqs
        return musicas
    except Exception as e:
        print(f"❌ Erro ao carregar músicas do banco: {e}")
        return {}

# --------- PROCESSAMENTO DE ÁUDIO ------------------

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

def plotar_spectrograma(y, sr, titulo, salvar_em=None):
    plt.figure(figsize=(10, 4))
    S = librosa.stft(y)
    S_db = librosa.amplitude_to_db(np.abs(S), ref=np.max)
    librosa.display.specshow(S_db, sr=sr, x_axis='time', y_axis='hz', cmap='magma')
    plt.colorbar(format="%+2.0f dB")
    plt.title(f"Spectrograma: {titulo}")
    plt.tight_layout()
    if salvar_em is None:
        salvar_em = f"/home/jovyan/work/cache/{titulo}_spectrograma.png"
    if salvar_em:
        plt.savefig(salvar_em)
        print(f"📸 Espectrograma salvo em: {salvar_em}")
    else:
        plt.show()
    plt.close()

# ---------- RECOMENDAÇÃO DE MÚSICAS ------------------

def comparar_musicas(vetor1, vetor2):
    return euclidean(vetor1, vetor2)

def recomendar_para_nova_musica(nome_nova, vetor_nova):
    musicas_banco = carregar_musicas_do_banco()
    distancias = []
    
    for nome_ref, vetor_ref in musicas_banco.items():
        if nome_ref == nome_nova:
            continue  # evita comparar com a própria música
        d = comparar_musicas(vetor_nova, vetor_ref)
        distancias.append((nome_ref, d))

    distancias.sort(key=lambda x: x[1])
    
    if distancias:
        recomendado = distancias[0]
        print(f"🎯 Música mais similar à '{nome_nova}': '{recomendado[0]}' (distância: {recomendado[1]:.2f})")
    else:
        print(f"⚠️ Nenhuma outra música no banco para comparar com '{nome_nova}'.")

# ---------- PROCESSAMENTO EM LOTE ------------------

def processar_completo(pasta):
    for arquivo in os.listdir(pasta):
        if arquivo.endswith(('.mp3', '.wav')):
            caminho = os.path.join(pasta, arquivo)
            print(f"\n🎧 Processando: {arquivo}")
            try:
                _, _, y, sr = extrair_fft(caminho)
                plotar_spectrograma(y, sr, arquivo)

                caracteristicas = extrair_caracteristicas(caminho)
                inserir_musica_banco(arquivo, caminho, caracteristicas)
                recomendar_para_nova_musica(arquivo, caracteristicas)

            except Exception as e:
                print(f"❌ Erro ao processar '{arquivo}': {e}")

# ---------- EXECUÇÃO PRINCIPAL ------------------

if __name__ == "__main__":
    criar_tabela()
    pasta = "/home/jovyan/work/audio"  # caminho dentro do container ou máquina local
    if not os.path.exists(pasta):
        print(f"❌ Caminho não encontrado: {pasta}")
    else:
        processar_completo(pasta)
