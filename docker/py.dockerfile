FROM python:3.11

WORKDIR /usr/src/app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt



CMD [ "python", "./main.py" ]

