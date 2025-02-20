FROM python:3.9

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt
COPY ./server.py /code/server.py
COPY ./AuthKey_54QRS283BA.p8 /code/AuthKey_54QRS283BA.p8

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "80"]
