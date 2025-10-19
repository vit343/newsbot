import asyncio
import aiohttp
import feedparser
import logging
import os
from natasha import Segmenter, NewsEmbedding, NewsMorphTagger, MorphVocab, Doc
import re
from datetime import datetime, timedelta
from typing import List, Dict, Set
import json
from dataclasses import dataclass
import hashlib
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Инициализация Natasha
segmenter = Segmenter()
emb = NewsEmbedding()
morph_tagger = NewsMorphTagger(emb)
morph_vocab = MorphVocab()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# Словарь синонимов
SYNONYMS = {
    'банк': ['банк', 'банковский', 'кредитное учреждение'],
    'инфляция': ['инфляция', 'рост цен', 'подорожание'],
    'кризис': ['кризис', 'спад', 'рецессия'],
}

def normalize_text_natasha(text: str) -> set[str]:
    doc = Doc(text.lower())
    doc.segment(segmenter)
    doc.tag_morph(morph_tagger)
    lemmas = set()
    for token in doc.tokens:
        token.lemmatize(morph_vocab)
        if re.match(r'\w+', token.text):
            lemmas.add(token.lemma)
    return lemmas

def match_with_synonyms(title: str, keywords: list[str]) -> bool:
    lemmas = normalize_text_natasha(title)
    for keyword in keywords:
        doc = Doc(keyword.lower())
        doc.segment(segmenter)
        doc.tag_morph(morph_tagger)
        if doc.tokens:
            doc.tokens[0].lemmatize(morph_vocab)
            lemma = doc.tokens[0].lemma
        else:
            lemma = keyword.lower()
        all_forms = {lemma} | set(SYNONYMS.get(lemma, []))
        if lemmas & all_forms:
            return True
    return False

@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    priority: int
    category: str
    timestamp: datetime
    hash: str

class RussianMarketNewsBot:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.seen_news: Set[str] = set()
        self.is_running = False
        self.config_file = "rss_sources.json"
        self.filter_file = "news_filters.json"
        
        self.rss_sources = self.load_sources()
        self.filters = self.load_filters()
        
        self.critical_keywords = [
            'ключевая ставка', 'санкции', 'газпром', 'сбербанк', 'лукойл', 'роснефт',
            'цб рф', 'банк россии', 'набиуллина', 'мишустин', 'силуанов',
            'курс рубля', 'нефть', 'золото', 'инфляция'
        ]
        
        self.tracked_companies = [
            'газпром', 'сбербанк', 'лукойл', 'роснефть', 'норникель',
            'яндекс', 'тинькофф', 'вымпелком', 'мтс', 'мегафон',
            'северсталь', 'нлмк', 'новатэк', 'магнит', 'х5',
            'сургутнефтегаз', 'татнефт', 'алроса', 'полюс', 'фосагро'
        ]
    
    def load_sources(self):
        default_sources = {
            "Интерфакс": {
                "url": "https://www.interfax.ru/rss.asp",
                "category": "Интерфакс",
                "priority": 2,
                "keywords": [],
                "enabled": True
            },
            "РБК": {
                "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
                "category": "РБК",
                "priority": 2,
                "keywords": [],
                "enabled": True
            }
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Ошибка загрузки источников: {e}")
                return default_sources
        return default_sources
    
    def save_sources(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.rss_sources, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Ошибка сохранения источников: {e}")
    
    def load_filters(self):
        default_filters = {
            'whitelist': [],
            'blacklist': []
        }
        
        if os.path.exists(self.filter_file):
            try:
                with open(self.filter_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Ошибка загрузки фильтров: {e}")
                return default_filters
        return default_filters
    
    def save_filters(self):
        try:
            with open(self.filter_file, 'w', encoding='utf-8') as f:
                json.dump(self.filters, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Ошибка сохранения фильтров: {e}")
    
    def calculate_priority(self, title: str, description: str, source_priority: int) -> int:
        text = f"{title} {description}".lower()
        
        for keyword in self.critical_keywords:
            if keyword in text:
                return 1
        
        for company in self.tracked_companies:
            if company in text:
                return min(source_priority, 2)
        
        return source_priority
    
    def apply_filters(self, title: str) -> bool:
        title_lower = title.lower()
        
        if self.filters['whitelist']:
            if not any(word.lower() in title_lower for word in self.filters['whitelist']):
                return False
        
        if self.filters['blacklist']:
            if any(word.lower() in title_lower for word in self.filters['blacklist']):
                return False
        
        return True
    
    async def fetch_rss_feed(self, session: aiohttp.ClientSession, source_name: str, source_config: dict) -> List[NewsItem]:
        if not source_config.get('enabled', True):
            return []
        
        try:
            async with session.get(source_config['url'], timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    logging.error(f"Ошибка загрузки {source_name}: HTTP {response.status}")
                    return []
                
                content = await response.text()
                feed = feedparser.parse(content)
                
                news_items = []
                for entry in feed.entries[:10]:
                    try:
                        title = entry.get('title', '')
                        link = entry.get('link', '')
                        description = entry.get('description', '')
                        
                        if not title or not link:
                            continue
                        
                        if not self.apply_filters(title):
                            continue
                        
                        news_hash = hashlib.md5(link.encode()).hexdigest()
                        if news_hash in self.seen_news:
                            continue
                        
                        published = entry.get('published_parsed')
                        if published:
                            pub_date = datetime(*published[:6])
                            if datetime.now() - pub_date > timedelta(hours=24):
                                continue
                        else:
                            pub_date = datetime.now()
                        
                        priority = self.calculate_priority(title, description, source_config.get('priority', 3))
                        
                        news_item = NewsItem(
                            title=title,
                            url=link,
                            source=source_name,
                            priority=priority,
                            category=source_config.get('category', source_name),
                            timestamp=pub_date,
                            hash=news_hash
                        )
                        
                        self.seen_news.add(news_hash)
                        news_items.append(news_item)
                        
                    except Exception as e:
                        logging.error(f"Ошибка обработки новости из {source_name}: {e}")
                        continue
                
                return news_items
                
        except Exception as e:
            logging.error(f"Ошибка загрузки RSS {source_name}: {e}")
            return []
    
    def format_news_message(self, news: NewsItem) -> str:
        priority_emoji = {1: '🚨', 2: '⚡', 3: '📊', 4: '📰'}
        category_emoji = {
            'ЦБ РФ': '🏦',
            'Кремль': '🏛️',
            'РБК': '📺',
            'Интерфакс': '📡',
            'Ведомости': '📰',
            'Коммерсант': '💼',
            'Финмаркет': '📈',
            'Банки.ру': '🏧'
        }
        
        emoji = priority_emoji.get(news.priority, '📰')
        source_emoji = category_emoji.get(news.category, '📰')
        
        message = f"{emoji} {source_emoji} <b>{news.source}</b>\n\n"
        message += f"{news.title}\n\n"
        message += f"🔗 {news.url}\n"
        message += f"⏰ {news.timestamp.strftime('%H:%M:%S')}"
        
        return message
    
    async def send_telegram_message(self, session: aiohttp.ClientSession, message: str):
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }
            
            async with session.post(url, json=data) as response:
                if response.status != 200:
                    logging.error(f"Ошибка отправки в Telegram: {await response.text()}")
                else:
                    logging.info(f"✅ Сообщение отправлено")
                    
        except Exception as e:
            logging.error(f"Ошибка отправки сообщения: {e}")
    
    async def check_all_sources(self):
        async with aiohttp.ClientSession() as session:
            tasks = []
            for source_name, source_config in self.rss_sources.items():
                tasks.append(self.fetch_rss_feed(session, source_name, source_config))
            
            all_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            all_news = []
            for result in all_results:
                if isinstance(result, list):
                    all_news.extend(result)
            
            all_news.sort(key=lambda x: x.priority)
            
            for news in all_news:
                if not self.is_running:
                    break
                message = self.format_news_message(news)
                await self.send_telegram_message(session, message)
                
                if news.priority == 1:
                    await asyncio.sleep(0.5)
                else:
                    await asyncio.sleep(2)
    
    async def run_monitoring(self, interval_minutes: int = 2):
        logging.info(f"🚀 Запуск мониторинга российского фондового рынка (интервал: {interval_minutes} мин)")
        self.is_running = True
        
        while self.is_running:
            try:
                await self.check_all_sources()
                logging.info(f"✅ Цикл проверки завершен. Следующая проверка через {interval_minutes} мин.")
                
                for _ in range(interval_minutes * 60):
                    if not self.is_running:
                        break
                    await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"❌ Ошибка в основном цикле: {e}")
                await asyncio.sleep(60)
    
    def stop_monitoring(self):
        self.is_running = False
        logging.info("⏹️ Мониторинг остановлен")

async def main():
    # Получение настроек из переменных окружения
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    interval = int(os.getenv('CHECK_INTERVAL_MINUTES', '2'))
    
    if not bot_token or not chat_id:
        logging.error("❌ Не указаны TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID в переменных окружения")
        return
    
    # Запуск HTTP сервера для предотвращения засыпания
    from aiohttp import web
    
    async def health_check(request):
        return web.Response(text="✅ Bot is alive and working!")
    
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv('PORT', '8080'))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"🌐 HTTP сервер запущен на порту {port}")
    
    # Запуск бота
    bot = RussianMarketNewsBot(bot_token, chat_id)
    
    try:
        await bot.run_monitoring(interval)
    except KeyboardInterrupt:
        logging.info("⏹️ Получен сигнал остановки")
        bot.stop_monitoring()
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())

