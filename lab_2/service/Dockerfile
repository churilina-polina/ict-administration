# Базовый образ: тонкий Python 3.12
FROM python:3.12-slim

# Рабочая папка внутри контейнера
WORKDIR /app

# Сначала зависимости — так Docker кеширует слой и не переустанавливает их при каждом изменении кода
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Теперь сам код
COPY app.py .

# Сервис слушает порт 8000
EXPOSE 8000

# Команда запуска
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
