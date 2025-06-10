FROM python:3.11

WORKDIR /app

COPY app/requirements.txt .

RUN python -m pip install --upgrade pip

RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app/


CMD [ "python", "./main.py" ]

