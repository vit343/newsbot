# Указываем базовый образ Python
FROM python:3.10-slim

# Создаём рабочую директорию
WORKDIR /app

# Копируем все файлы проекта в контейнер
COPY . /app

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Указываем порт (если нужен для вебхука или Flask)
EXPOSE 80

# Команда запуска бота
CMD ["python", "main.py"]


