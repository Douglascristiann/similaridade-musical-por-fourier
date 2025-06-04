FROM python:3.11

WORKDIR /usr/src/app

COPY requirements.txt /home/administrador/project/similaridade-musical-por-fourier/app
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD [ "python", "./main.py" ]

