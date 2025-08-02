from mysql.connector import Error
import mysql.connector

DB_TABLE_NAME = "tb_musicas_v3" # Usaremos a nova tabela v2
EXPECTED_FEATURE_LENGTH = 40 * 3 + 12 + 6 + 6 + 1 + 1 + 1 + 1 + 1  # = 161

from db_connect import DB_CONFIG

def conectar():
    """Estabelece uma conexão com o banco de dados MySQL."""
    return mysql.connector.connect(**DB_CONFIG)

# def musica_existe(titulo):
#     """Verifica se uma música já existe na tabela do banco de dados."""
#     with conectar() as conn:
#         with conn.cursor() as cur:
#             cur.execute(f"SELECT 1 FROM {DB_TABLE_NAME} WHERE nome = %s", (titulo,))
#             return cur.fetchone() is not titulo
def links_nao_existentes(lista_links):
    """
    Retorna apenas os links do YouTube que NÃO existem na tabela do banco de dados.
    """
    if not lista_links:
        return []

    placeholders = ','.join(['%s'] * len(lista_links))

    query = (
        f"SELECT link_youtube FROM {DB_TABLE_NAME} "
        f"WHERE link_youtube IN ({placeholders})"
    )

    existentes = set()
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(query, lista_links)
            for (link,) in cur.fetchall():
                existentes.add(link)

    return [link for link in lista_links if link not in existentes]


def inserir_musica(nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube):
    """Insere as informações de uma música e suas características no banco de dados."""
    if len(caracteristicas) != EXPECTED_FEATURE_LENGTH:
        print(f"❌ Erro: Características da música '{nome}' têm tamanho incorreto ({len(caracteristicas)}). Esperado: {EXPECTED_FEATURE_LENGTH}. Não será inserida na '{DB_TABLE_NAME}'.")
        return

    if links_nao_existentes(link_youtube):
        print(f"⚠️ Música '{titulo}' já cadastrada em '{DB_TABLE_NAME}'.\n🔗 Link: '{link_youtube}'")
        return

    carac_str = ",".join(map(str, caracteristicas))
    with conectar() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {DB_TABLE_NAME} (nome, caracteristicas, artista, titulo, album, genero, capa_album, link_youtube)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                nome,
                carac_str,
                artista or "Não Encontrado",
                titulo or "Não Encontrado",
                album or "Não Encontrado",
                genero or "Não Encontrado",
                capa_album or "Não Encontrado",
                link_youtube or "Não Encontrado"
            ))
            conn.commit()
            print(f"✅ Inserida no banco '{DB_TABLE_NAME}': {titulo}")
            print(f"🔗 Link da Musíca: {link_youtube}")

def carregar_musicas():
    """Carrega todas as músicas com características consistentes do banco de dados."""
    with conectar() as conn:
        with conn.cursor() as cur:
            # Filtra músicas com o número correto de características (garantindo consistência)
            cur.execute(f"SELECT nome, caracteristicas, artista, titulo, link_youtube FROM {DB_TABLE_NAME} WHERE LENGTH(caracteristicas) - LENGTH(REPLACE(caracteristicas, ',', '')) + 1 = {EXPECTED_FEATURE_LENGTH}")
            rows = cur.fetchall()
    return [(nome, list(map(float, carac.split(","))), artista, titulo, link) for nome, carac, artista, titulo, link in rows]