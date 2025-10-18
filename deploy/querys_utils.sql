show databases;

use dbmusicadata;

show tables;

select * from tb_musicas
limit 3000;

select	* from tb_nps;
select * from tb_usuarios;

SELECT
    t1.id,
    t1.user_id,
    t1.musica_id,
    t2.titulo,
    t1.rating,
    t1.channel,
    t1.alg_vencedor,
    t1.created_at,
    t1.updated_at,
    t1.event_type,
    t1.participant_id,
    t1.seed_id,
    t1.seed_title,
    t1.cand_id,
    t1.cand_title,
    t1.in_topk,
    t1.user_sim,
    t1.user_sim_score,
    t1.nps_score,
    t1.nps_comment
FROM
    tb_nps AS t1
INNER JOIN
    tb_musicas AS t2 ON t1.musica_id = t2.id;

SELECT
    t1.id,
    t1.user_id,
    t1.musica_id,
    t1.rating,
    t1.channel,
    t1.alg_vencedor,
    t1.created_at,
    t1.updated_at,
    t1.event_type,
    t1.participant_id,
    t1.seed_id,
    t1.seed_title,
    t1.cand_id,
    t1.cand_title,
    t1.in_topk,
    t1.user_sim,
    t1.user_sim_score,
    t1.nps_score,
    t1.nps_comment,
    t2.titulo
FROM
    tb_nps AS t1
INNER JOIN
    tb_musicas AS t2 ON t1.musica_id = t2.id
WHERE
    t1.channel = 'user_test_nps';



SELECT * FROM tb_musicas WHERE link_spotify IS NULL; 
SELECT * FROM tb_musicas WHERE link_youtube IS NULL;

SELECT titulo, COUNT(*) AS quantidade
FROM tb_musicas
GROUP BY titulo
HAVING COUNT(*) > 1;

select COUNT(*) from tb_musicas where genero = '';

CREATE TABLE tb_musicas_teste LIKE tb_musicas;

INSERT INTO tb_musicas_teste SELECT * FROM tb_musicas;
-- Ajuste o nome da tabela se necessário (ex.: tb_musicas)



SELECT id, titulo, artista, album
FROM tb_musicas
WHERE (titulo, artista, album) IN (
  SELECT titulo, artista, album
  FROM tb_musicas
  GROUP BY titulo, artista, album
  HAVING COUNT(*) > 1
)
ORDER BY titulo, artista, album, id;



select * from tb_musicas
limit 3000;


select COUNT(*) from tb_musicas where genero = 'Desconhecido';


select * from tb_musicas 
limit 3000;


UPDATE tb_musicas
SET genero = 'Desconhecido'
WHERE genero = '';




#___________________reorganizar os IDS_________________________
#-- ⚠️ Etapa 0: (Opcional) Faça backup antes de rodar isso!

#-- 1. Remover temporariamente o AUTO_INCREMENT
#ALTER TABLE tb_musicas MODIFY COLUMN id INT;

#-- 2. Inicializar variável para nova contagem
#SET @novo = 0;

#-- 3. Criar tabela auxiliar temporária com nova ordem
#CREATE TEMPORARY TABLE nova_ordem (
#  antigo_id INT,
#  novo_id INT
#);

#-- 4. Preencher nova_ordem com IDs sequenciais
#INSERT INTO nova_ordem (antigo_id, novo_id)
#SELECT id, (@novo := @novo + 1)
#FROM tb_musicas
#ORDER BY id;

#-- 5. Atualizar os IDs na tabela original
#UPDATE tb_musicas
#JOIN nova_ordem ON tb_musicas.id = nova_ordem.antigo_id
#SET tb_musicas.id = nova_ordem.novo_id;

#-- 6. Apagar tabela auxiliar
#DROP TEMPORARY TABLE nova_ordem;

#-- 7. Restaurar AUTO_INCREMENT
#ALTER TABLE tb_usuarios AUTO_INCREMENT = 0;

#8 --- partir do ultimo id ajuste auto_increment

#ALTER TABLE tb_musicas AUTO_INCREMENT = las;

#--------------------------------------------------
# outros
#DELETE FROM tb_musicas WHERE id = 1561;

#DELETE FROM tb_musicas
#WHERE id BETWEEN 1563 AND 1567;

#DELETE FROM tb_musicas
#WHERE id IN (
#  SELECT id FROM (
#    SELECT id,
#           ROW_NUMBER() OVER (PARTITION BY artista, titulo ORDER BY id) AS rn
#    FROM tb_musicas
#  ) AS temp
#  WHERE rn > 1
#);


