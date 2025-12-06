FROM python:3.8.10

COPY ./requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

WORKDIR /app

EXPOSE 60051-60059

ENTRYPOINT ["python", "proxy.py"]
