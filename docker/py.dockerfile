FROM quay.io/jupyter/base-notebook

WORKDIR /home/jovyan/work

COPY app/requirements.txt .

RUN python -m pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /home/jovyan/work/

# Corrige permissões para que jovyan possa escrever
USER root
RUN apt update && apt install -y ffmpeg
RUN chown -R jovyan:users /home/jovyan
USER jovyan
