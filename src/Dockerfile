FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt requirements.txt
# Очищаем кэш pip и переустанавливаем зависимости
RUN pip cache purge && \
    pip uninstall -y openai httpx && \
    pip install --no-cache-dir httpx==0.27.2 && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]