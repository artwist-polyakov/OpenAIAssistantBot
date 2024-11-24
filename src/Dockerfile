FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Добавляем правильную обработку сигналов
STOPSIGNAL SIGTERM

# Используем tini как init процесс
RUN apt-get update && apt-get install -y tini
ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["python", "bot.py"]