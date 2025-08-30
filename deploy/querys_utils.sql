show databases;

use dbmusicadata;

show tables;

select * from tb_musicas;

ALTER TABLE tb_musicas
  ADD COLUMN link_spotify TEXT NULL AFTER link_youtube;
  
SELECT * FROM tb_musicas WHERE link_spotify IS NULL; 

SELECT * FROM tb_musicas WHERE link_youtube IS NULL;
