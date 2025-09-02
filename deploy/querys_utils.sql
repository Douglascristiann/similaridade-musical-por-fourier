show databases;

use dbmusicadata;

show tables;

select * from tb_musicas;
select	* from tb_nps;
select * from tb_usuarios;


SELECT * FROM tb_musicas WHERE link_spotify IS NULL; 
SELECT * FROM tb_musicas WHERE link_youtube IS NULL;



# outros
#DELETE FROM tb_musicas WHERE id BETWEEN n AND n;
