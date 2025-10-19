# 🚀 Деплой Telegram бота на Render.com

## 📋 Подготовка

### 1. Получите токен бота
1. Откройте Telegram и найдите `@BotFather`
2. Отправьте `/newbot` и следуйте инструкциям
3. Скопируйте полученный токен (выглядит как `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Узнайте ваш Chat ID
1. Найдите бота `@userinfobot` в Telegram
2. Отправьте `/start`
3. Скопируйте ваш Chat ID (число, например `123456789`)

## 🌐 Деплой на Render.com (Бесплатно)

### Шаг 1: Загрузите код на GitHub

1. Создайте репозиторий на [GitHub](https://github.com/new)
2. Загрузите все файлы из папки `D:\NEWS\news\`:
   - `bot_server.py` (серверная версия)
   - `requirements.txt`
   - `Dockerfile`
   - `rss_sources.json`
   - `news_filters.json`
   - `.gitignore`

**Важно:** НЕ загружайте файл `.env` с токенами!

### Шаг 2: Создайте Web Service на Render

1. Зайдите на [render.com](https://render.com) и зарегистрируйтесь
2. Нажмите **"New +"** → **"Web Service"**
3. Подключите ваш GitHub репозиторий
4. Заполните настройки:
   - **Name:** `news-bot` (любое имя)
   - **Region:** Frankfurt (ближе к РФ)
   - **Branch:** `main`
   - **Runtime:** `Docker`
   - **Instance Type:** `Free`

### Шаг 3: Настройте переменные окружения

В разделе **Environment Variables** добавьте:

```
TELEGRAM_BOT_TOKEN = ваш_токен_от_BotFather
TELEGRAM_CHAT_ID = ваш_chat_id
CHECK_INTERVAL_MINUTES = 2
```

### Шаг 4: Запустите бот

1. Нажмите **"Create Web Service"**
2. Подождите 5-10 минут (первый деплой)
3. В логах должно появиться: `🚀 Запуск мониторинга российского фондового рынка`

## ✅ Проверка работы

Бот должен начать отправлять новости в ваш Telegram каждые 2 минуты.

Пример сообщения:
```
⚡ 📡 Интерфакс

ЦБ РФ повысил ключевую ставку до 16%

🔗 https://www.interfax.ru/...
⏰ 14:30:45
```

## 🔧 Альтернативные хостинги

### Fly.io
```bash
# Установите flyctl
curl -L https://fly.io/install.sh | sh

# Войдите в аккаунт
flyctl auth login

# Запустите деплой
flyctl launch
flyctl secrets set TELEGRAM_BOT_TOKEN=your_token
flyctl secrets set TELEGRAM_CHAT_ID=your_chat_id
flyctl deploy
```

### Railway.app
1. Зайдите на [railway.app](https://railway.app)
2. Нажмите **"New Project"** → **"Deploy from GitHub"**
3. Выберите репозиторий
4. Добавьте переменные окружения в настройках

## 🛠️ Локальный запуск (для тестирования)

```bash
# Установите зависимости
pip install -r requirements.txt

# Скопируйте .env.example в .env
copy .env.example .env

# Отредактируйте .env и добавьте свои токены

# Запустите бота
python bot_server.py
```

## 📝 Настройка источников новостей

Отредактируйте `rss_sources.json` для добавления/удаления источников:

```json
{
  "РБК": {
    "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
    "category": "РБК",
    "priority": 2,
    "keywords": [],
    "enabled": true
  }
}
```

## 🎯 Фильтры новостей

Отредактируйте `news_filters.json`:

```json
{
  "whitelist": ["газпром", "сбербанк"],
  "blacklist": ["спорт", "погода"]
}
```

## 🐛 Решение проблем

### Бот не отправляет сообщения
- Проверьте токен бота
- Проверьте Chat ID
- Убедитесь, что вы написали боту `/start`

### Ошибка "Unauthorized"
- Токен неверный, получите новый у @BotFather

### Логи показывают ошибки RSS
- Некоторые источники могут быть недоступны из-за блокировок
- Удалите проблемные источники из `rss_sources.json`

## 💰 Лимиты бесплатного тарифа

**Render.com Free:**
- 750 часов/месяц
- Засыпает после 15 минут неактивности
- Пробуждается при запросе (бот работает постоянно, не засыпает)

**Важно:** Бесплатный тариф Render перезапускается раз в месяц. Данные не сохраняются между перезапусками.

## 📞 Поддержка

При возникновении проблем проверьте логи на Render.com в разделе **"Logs"**.
