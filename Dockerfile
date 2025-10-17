# Базовый образ Python 3.10
FROM python:3.10-slim

# Рабочая директория внутри контейнера
WORKDIR /app

# Копируем все файлы проекта в контейнер
COPY . /app

# Устанавливаем зависимости из requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Если бот использует Flask для вебхука, указываем порт
EXPOSE 80

# Команда запуска бота
CMD ["python", "main.py"]


