FROM python:3.10-slim-bullseye

WORKDIR /app

COPY requirements.txt requirements.txt
COPY  monitoring.py monitoring.py

RUN pip install -r requirements.txt

CMD ["python", "monitoring.py"]