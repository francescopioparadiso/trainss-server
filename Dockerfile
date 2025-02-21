FROM python:3.9

WORKDIR /code

RUN python -m venv venv && \
    . venv/bin/activate && \
    pip install --no-cache-dir -r requirements.txt

COPY ./requirements.txt /code/requirements.txt
COPY ./server.py /code/server.py

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "80"]
