# tests/test_consulta_insercao.py
import unittest
from unittest.mock import patch, MagicMock
from consulta_insercao import musicas_nao_existentes

class TestConsultaInsercao(unittest.TestCase):

    @patch("consulta_insercao.conectar")
    def test_musicas_nao_existentes_com_tuplas(self, mock_conectar):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("Existente", "Artista")]  # Simula retorno do banco
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conectar.return_value.__enter__.return_value = mock_conn

        titulos = [("Nova", "Artista"), ("Existente", "Artista")]
        resultado = musicas_nao_existentes(titulos)
        self.assertEqual(resultado, [("Nova", "Artista")])

    @patch("consulta_insercao.conectar")
    def test_musicas_nao_existentes_com_dicts(self, mock_conectar):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("Existente", "Artista")]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conectar.return_value.__enter__.return_value = mock_conn

        dicts = [
            {"titulo": "Nova", "artista": "Artista"},
            {"titulo": "Existente", "artista": "Artista"},
        ]
        resultado = musicas_nao_existentes(dicts)
        self.assertEqual(resultado, [("Nova", "Artista")])

if __name__ == "__main__":
    unittest.main()
