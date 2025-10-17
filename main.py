import asyncio
import aiohttp
import feedparser
import logging
from natasha import Segmenter, NewsEmbedding, NewsMorphTagger, MorphVocab, Doc
import re

# Инициализация Natasha
segmenter = Segmenter()
emb = NewsEmbedding()
morph_tagger = NewsMorphTagger(emb)
morph_vocab = MorphVocab()

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

from datetime import datetime, timedelta
import re
from typing import List, Dict, Set
import json
from dataclasses import dataclass, asdict
import hashlib
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import os
from pathlib import Path
import ctypes
from ctypes import wintypes
import winreg

@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    priority: int
    category: str
    timestamp: datetime
    hash: str

def is_dark_mode():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except Exception as e:
        logging.error(f"Ошибка проверки системной темы: {e}")
        return False

def set_dark_title_bar(window):
    if not is_dark_mode():
        logging.info("Системная тема светлая, тёмный заголовок не применяется.")
        return
    try:
        window.update()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = wintypes.BOOL(True)  # Используем True для активации тёмного режима
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value),
            ctypes.sizeof(value)
        )
        if hr != 0:
            logging.error(f"Ошибка DwmSetWindowAttribute (HRESULT: {hr})")
            value = wintypes.BOOL(True)
            hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                19,  # Альтернативный атрибут для старых версий
                ctypes.byref(value),
                ctypes.sizeof(value)
            )
            if hr != 0:
                logging.error(f"Ошибка DwmSetWindowAttribute с атрибутом 19 (HRESULT: {hr})")
            else:
                logging.info("Тёмный заголовок применён через атрибут 19.")
        else:
            logging.info("Тёмный заголовок успешно применён через атрибут 20.")
        
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        current_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if current_style & WS_EX_LAYERED:
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, current_style & ~WS_EX_LAYERED)
            logging.info("Удалён стиль WS_EX_LAYERED для устранения прозрачности.")
        
        window.update()
        ctypes.windll.user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0004)
        ctypes.windll.user32.UpdateWindow(hwnd)
        logging.info("Окно перерисовано для применения тёмного заголовка.")
    except Exception as e:
        logging.error(f"Ошибка установки тёмного заголовка: {e}")

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
            'яндекс', 'тинькофф', 'норникель', 'сургутнефтегаз', 'магнит', 'х5',
            'мтс', 'мегафон', 'вымпелком', 'северсталь', 'нлмк', 'новатэк',
            'дивиденды', 'делистинг', 'листинг', 'банкротство', 'слияние',
            'курс рубля', 'нефть', 'золото', 'инфляция'
        ]
        
        self.tracked_companies = [
            'газпром', 'сбербанк', 'лукойл', 'роснефт', 'норникель',
            'яндекс', 'тинькофф', 'вымпелком', 'мтс', 'мегафон',
            'северсталь', 'нлмк', 'новатэк', 'магнит', 'х5',
            'сургутнефтегаз', 'татнефт', 'алроса', 'полюс', 'фосагро'
        ]

    def load_sources(self):
        default_sources = {
            'cbr': {
                'url': 'https://www.cbr.ru/rss/main/',
                'priority': 1,
                'category': 'ЦБ РФ',
                'keywords': ['ключевая ставка', 'валютное регулирование', 'денежно-кредитная политика'],
                'enabled': True
            },
            'kremlin': {
                'url': 'http://kremlin.ru/events/president/news/rss',
                'priority': 1,
                'category': 'Кремль',
                'keywords': ['экономика', 'санкции', 'энергетика'],
                'enabled': True
            },
            'rbc': {
                'url': 'https://rbc.ru/rss/index.rss',
                'priority': 2,
                'category': 'РБК',
                'keywords': [],
                'enabled': True
            },
            'interfax': {
                'url': 'https://www.interfax.ru/rss.asp',
                'priority': 2,
                'category': 'Интерфакс',
                'keywords': [],
                'enabled': True
            },
            'vedomosti': {
                'url': 'https://www.vedomosti.ru/rss/news',
                'priority': 2,
                'category': 'Ведомости',
                'keywords': [],
                'enabled': True
            },
            'kommersant': {
                'url': 'https://www.kommersant.ru/RSS/main.xml',
                'priority': 2,
                'category': 'Коммерсант',
                'keywords': [],
                'enabled': True
            },
            'finmarket': {
                'url': 'https://www.finmarket.ru/rss/mainnews.xml',
                'priority': 2,
                'category': 'Финмаркет',
                'keywords': [],
                'enabled': True
            },
            'banki': {
                'url': 'https://www.banki.ru/xml/news.rss',
                'priority': 3,
                'category': 'Банки.ру',
                'keywords': ['банк', 'кредит', 'ипотека'],
                'enabled': True
            }
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Ошибка загрузки конфигурации: {e}")
                return default_sources
        return default_sources

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

    def save_sources(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.rss_sources, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Ошибка сохранения конфигурации: {e}")

    def calculate_priority(self, title: str, source_priority: int) -> int:
        title_lower = title.lower()
        
        critical_patterns = [
            'экстренно', 'срочно', 'breaking', 'чп', 'авария',
            'ключевая ставка', 'решение цб', 'санкции против',
            'приостановка торгов', 'делистинг', 'банкротство'
        ]
        
        for pattern in critical_patterns:
            if pattern in title_lower:
                return 1
                
        for company in self.tracked_companies:
            if company in title_lower:
                return min(source_priority, 2)
                
        for keyword in self.critical_keywords:
            if keyword in title_lower:
                return min(source_priority, 2)
                
        return source_priority

    def create_news_hash(self, title: str, url: str) -> str:
        return hashlib.md5(f"{title}{url}".encode()).hexdigest()

    def apply_filters(self, title: str) -> bool:
        title_lower = title.lower()
        
        if self.filters['blacklist']:
            for keyword in self.filters['blacklist']:
                if keyword.lower() in title_lower:
                    return False
                    
        if self.filters['whitelist']:
            for keyword in self.filters['whitelist']:
                if keyword.lower() in title_lower:
                    return True
            return False
            
        return True

    async def fetch_rss_feed(self, session: aiohttp.ClientSession, source_name: str, source_config: dict) -> List[NewsItem]:
        if not source_config.get('enabled', True):
            return []
            
        try:
            async with session.get(source_config['url'], timeout=10) as response:
                if response.status == 200:
                    content = await response.text()
                    feed = feedparser.parse(content)
                    
                    news_items = []
                    for entry in feed.entries[:10]:
                        title = entry.get('title', '')
                        url = entry.get('link', '')
                        
                        if not title or not url:
                            continue
                            
                        if not self.apply_filters(title):
                            continue
                            
                        news_hash = self.create_news_hash(title, url)
                        if news_hash in self.seen_news:
                            continue
                            
                        priority = self.calculate_priority(title, source_config['priority'])
                        
                        if source_config['keywords']:
                            if not any(keyword.lower() in title.lower() for keyword in source_config['keywords']):
                                continue
                        
                        news_item = NewsItem(
                            title=title,
                            url=url,
                            source=source_config['category'],
                            priority=priority,
                            category=source_config['category'],
                            timestamp=datetime.now(),
                            hash=news_hash
                        )
                        
                        news_items.append(news_item)
                        self.seen_news.add(news_hash)
                    
                    return news_items
                    
        except Exception as e:
            logging.error(f"Ошибка получения RSS {source_name}: {e}")
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
        logging.info(f"Запуск мониторинга российского фондового рынка (интервал: {interval_minutes} мин)")
        self.is_running = True
        
        while self.is_running:
            try:
                await self.check_all_sources()
                for _ in range(interval_minutes * 60):
                    if not self.is_running:
                        break
                    await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Ошибка в основном цикле: {e}")
                await asyncio.sleep(60)

    def stop_monitoring(self):
        self.is_running = False

class FilterDialog:
    def __init__(self, parent, title, filter_list):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.geometry("400x300")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        set_dark_title_bar(self.dialog)
        self.filter_list = filter_list.copy()
        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self.dialog, padding="10", style='Dark.TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(main_frame, bg='#2b2b2b', fg='#ffffff', selectbackground='#3a3f44', height=10, selectmode=tk.MULTIPLE)
        self.listbox.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        for item in self.filter_list:
            self.listbox.insert(tk.END, item)

        entry_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        entry_frame.pack(fill=tk.X, pady=(0, 10))
        self.entry_var = tk.StringVar()
        ttk.Entry(entry_frame, textvariable=self.entry_var, style='Dark.TEntry').pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(entry_frame, text="Добавить", command=self.add_item, style='Dark.TButton').pack(side=tk.LEFT)

        button_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="Удалить", command=self.delete_item, style='Dark.TButton').pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Сохранить", command=self.save, style='Dark.TButton').pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Отмена", command=self.dialog.destroy, style='Dark.TButton').pack(side=tk.RIGHT)

    def add_item(self):
        item = self.entry_var.get().strip()
        if item and item not in self.filter_list:
            self.filter_list.append(item)
            self.listbox.insert(tk.END, item)
            self.entry_var.set("")

    def delete_item(self):
        selections = self.listbox.curselection()
        if selections:
            for index in reversed(selections):
                item = self.listbox.get(index)
                self.filter_list.remove(item)
                self.listbox.delete(index)

    def save(self):
        self.result = self.filter_list
        self.dialog.destroy()

class NewsSourceDialog:
    def __init__(self, parent, title="Добавить источник", source_data=None):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.geometry("500x400")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.geometry("+%d+%d" % (parent.winfo_rootx() + 50, parent.winfo_rooty() + 50))
        set_dark_title_bar(self.dialog)
        self.create_widgets(source_data)
        
    def create_widgets(self, source_data):
        main_frame = ttk.Frame(self.dialog, padding="10", style='Dark.TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text="Имя источника:", style='Dark.TLabel').pack(anchor=tk.W, pady=(0, 5))
        self.name_var = tk.StringVar()
        ttk.Entry(main_frame, textvariable=self.name_var, width=50, style='Dark.TEntry').pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(main_frame, text="URL RSS ленты:", style='Dark.TLabel').pack(anchor=tk.W, pady=(0, 5))
        self.url_var = tk.StringVar()
        ttk.Entry(main_frame, textvariable=self.url_var, width=50, style='Dark.TEntry').pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(main_frame, text="Категория:", style='Dark.TLabel').pack(anchor=tk.W, pady=(0, 5))
        self.category_var = tk.StringVar()
        ttk.Entry(main_frame, textvariable=self.category_var, width=50, style='Dark.TEntry').pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(main_frame, text="Приоритет:", style='Dark.TLabel').pack(anchor=tk.W, pady=(0, 5))
        priority_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        priority_frame.pack(fill=tk.X, pady=(0, 10))
        self.priority_var = tk.IntVar(value=2)
        ttk.Radiobutton(priority_frame, text="1 - Критично", variable=self.priority_var, value=1, style='Dark.TRadiobutton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(priority_frame, text="2 - Важно", variable=self.priority_var, value=2, style='Dark.TRadiobutton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Radiobutton(priority_frame, text="3 - Умеренно", variable=self.priority_var, value=3, style='Dark.TRadiobutton').pack(side=tk.LEFT)
        
        ttk.Label(main_frame, text="Ключевые слова (через запятую):", style='Dark.TLabel').pack(anchor=tk.W, pady=(0, 5))
        self.keywords_text = scrolledtext.ScrolledText(main_frame, height=4, width=50, bg='#2b2b2b', fg='#ffffff', insertbackground='white')
        self.keywords_text.pack(fill=tk.X, pady=(0, 10))
        
        self.enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(main_frame, text="Источник активен", variable=self.enabled_var, style='Dark.TCheckbutton').pack(anchor=tk.W, pady=(0, 10))
        
        button_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        button_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(button_frame, text="Сохранить", command=self.save_source, style='Dark.TButton').pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="Отмена", command=self.dialog.destroy, style='Dark.TButton').pack(side=tk.RIGHT)
        
        if source_data:
            self.name_var.set(source_data[0])
            self.url_var.set(source_data[1].get('url', ''))
            self.category_var.set(source_data[1].get('category', ''))
            self.priority_var.set(source_data[1].get('priority', 2))
            self.keywords_text.insert('1.0', ', '.join(source_data[1].get('keywords', [])))
            self.enabled_var.set(source_data[1].get('enabled', True))
        
    def save_source(self):
        name = self.name_var.get().strip()
        url = self.url_var.get().strip()
        category = self.category_var.get().strip()
        
        if not name or not url or not category:
            messagebox.showerror("Ошибка", "Заполните все обязательные поля!")
            return
            
        keywords_text = self.keywords_text.get('1.0', tk.END).strip()
        keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()] if keywords_text else []
        
        self.result = (name, {
            'url': url,
            'category': category,
            'priority': self.priority_var.get(),
            'keywords': keywords,
            'enabled': self.enabled_var.get()
        })
        
        self.dialog.destroy()

class NewsMonitorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Российский фондовый рынок - Мониторинг новостей")
        self.root.geometry("800x600")
        self.root.configure(bg='#1c2526')
        set_dark_title_bar(self.root)
        
        self.bot = None
        self.bot_task = None
        self.config_file = "bot_config.json"
        
        style = ttk.Style()
        style.theme_create("dark", parent="alt", settings={
            "TFrame": {"configure": {"background": "#1c2526"}},
            "Dark.TFrame": {"configure": {"background": "#1c2526"}},
            "TLabel": {"configure": {"background": "#1c2526", "foreground": "#ffffff"}},
            "Dark.TLabel": {"configure": {"background": "#1c2526", "foreground": "#ffffff"}},
            "TEntry": {"configure": {"fieldbackground": "#2b2b2b", "foreground": "#ffffff", "insertcolor": "white"}},
            "Dark.TEntry": {"configure": {"fieldbackground": "#2b2b2b", "foreground": "#ffffff", "insertcolor": "white"}},
            "TButton": {"configure": {"background": "#3a3f44", "foreground": "#ffffff"}},
            "Dark.TButton": {"configure": {"background": "#3a3f44", "foreground": "#ffffff"}},
            "TRadiobutton": {"configure": {"background": "#1c2526", "foreground": "#ffffff"}},
            "Dark.TRadiobutton": {"configure": {"background": "#1c2526", "foreground": "#ffffff"}},
            "TCheckbutton": {"configure": {"background": "#1c2526", "foreground": "#ffffff"}},
            "Dark.TCheckbutton": {"configure": {"background": "#1c2526", "foreground": "#ffffff"}},
            "TNotebook": {"configure": {"background": "#1c2526", "tabmargins": [2, 5, 2, 0]}},
            "TNotebook.Tab": {
                "configure": {"background": "#3a3f44", "foreground": "#ffffff", "padding": [5, 1]},
                "map": {"background": [("selected", "#1c2526")], "foreground": [("selected", "#ffffff")]}
            },
            "Treeview": {
                "configure": {"background": "#2b2b2b", "foreground": "#ffffff", "fieldbackground": "#2b2b2b"}
            },
            "Treeview.Heading": {
                "configure": {"background": "#3a3f44", "foreground": "#ffffff"}
            }
        })
        style.theme_use("dark")
        
        self.create_widgets()
        self.load_config()
        
    def create_widgets(self):
        menubar = tk.Menu(self.root, bg='#1c2526', fg='#ffffff')
        self.root.config(menu=menubar)
        
        file_menu = tk.Menu(menubar, tearoff=0, bg='#1c2526', fg='#ffffff')
        menubar.add_cascade(label="Файл", menu=file_menu)
        file_menu.add_command(label="Загрузить конфигурацию", command=self.load_config)
        file_menu.add_command(label="Сохранить конфигурацию", command=self.save_config)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.root.quit)
        
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.create_settings_tab(notebook)
        self.create_sources_tab(notebook)
        self.create_logs_tab(notebook)
        
    def create_settings_tab(self, notebook):
        settings_frame = ttk.Frame(notebook, style='Dark.TFrame')
        notebook.add(settings_frame, text="Настройки")
        
        bot_frame = ttk.LabelFrame(settings_frame, text="Настройки Telegram бота", padding="10", style='Dark.TFrame')
        bot_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(bot_frame, text="Токен бота:", style='Dark.TLabel').pack(anchor=tk.W, pady=(0, 5))
        self.token_var = tk.StringVar()
        ttk.Entry(bot_frame, textvariable=self.token_var, width=60, show="*", style='Dark.TEntry').pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(bot_frame, text="ID чата/канала:", style='Dark.TLabel').pack(anchor=tk.W, pady=(0, 5))
        self.chat_id_var = tk.StringVar()
        ttk.Entry(bot_frame, textvariable=self.chat_id_var, width=60, style='Dark.TEntry').pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(bot_frame, text="Интервал проверки (минуты):", style='Dark.TLabel').pack(anchor=tk.W, pady=(0, 5))
        self.interval_var = tk.IntVar(value=2)
        ttk.Spinbox(bot_frame, from_=1, to=60, textvariable=self.interval_var, width=10, style='Dark.TEntry').pack(anchor=tk.W, pady=(0, 10))
        
        filters_frame = ttk.LabelFrame(settings_frame, text="Фильтры новостей", padding="10", style='Dark.TFrame')
        filters_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(filters_frame, text="Белый список:", style='Dark.TLabel').pack(anchor=tk.W, pady=(0, 5))
        self.whitelist_box = tk.Listbox(filters_frame, bg='#2b2b2b', fg='#ffffff', selectbackground='#3a3f44', height=5)
        self.whitelist_box.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(filters_frame, text="Редактировать белый список", command=lambda: self.edit_filter('whitelist'), style='Dark.TButton').pack(anchor=tk.W, pady=(0, 10))
        
        ttk.Label(filters_frame, text="Черный список:", style='Dark.TLabel').pack(anchor=tk.W, pady=(0, 5))
        self.blacklist_box = tk.Listbox(filters_frame, bg='#2b2b2b', fg='#ffffff', selectbackground='#3a3f44', height=5)
        self.blacklist_box.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(filters_frame, text="Редактировать черный список", command=lambda: self.edit_filter('blacklist'), style='Dark.TButton').pack(anchor=tk.W, pady=(0, 10))
        
        control_frame = ttk.Frame(settings_frame, style='Dark.TFrame')
        control_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.start_button = ttk.Button(control_frame, text="Запустить мониторинг", command=self.start_monitoring, style='Dark.TButton')
        self.start_button.pack(side=tk.LEFT, padx=(0, 10))
        
        self.stop_button = ttk.Button(control_frame, text="Остановить", command=self.stop_monitoring, state=tk.DISABLED, style='Dark.TButton')
        self.stop_button.pack(side=tk.LEFT)
        
        self.status_var = tk.StringVar(value="Остановлен")
        status_label = ttk.Label(control_frame, textvariable=self.status_var, style='Dark.TLabel')
        status_label.pack(side=tk.RIGHT)
        ttk.Label(control_frame, text="Статус:", style='Dark.TLabel').pack(side=tk.RIGHT, padx=(0, 5))
        
    def edit_filter(self, filter_type):
        filter_list = self.bot.filters[filter_type] if self.bot else []
        dialog = FilterDialog(self.root, f"Редактировать {filter_type}", filter_list)
        self.root.wait_window(dialog.dialog)
        if dialog.result is not None:
            self.bot.filters[filter_type] = dialog.result
            self.update_filter_listbox(filter_type)
            self.bot.save_filters()
            logging.info(f"{filter_type} обновлен: {dialog.result}")

    def update_filter_listbox(self, filter_type):
        listbox = self.whitelist_box if filter_type == 'whitelist' else self.blacklist_box
        listbox.delete(0, tk.END)
        for item in self.bot.filters[filter_type]:
            listbox.insert(tk.END, item)

    def create_sources_tab(self, notebook):
        sources_frame = ttk.Frame(notebook, style='Dark.TFrame')
        notebook.add(sources_frame, text="Источники новостей")
        
        toolbar = ttk.Frame(sources_frame, style='Dark.TFrame')
        toolbar.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        ttk.Button(toolbar, text="Добавить источник", command=self.add_source, style='Dark.TButton').pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(toolbar, text="Редактировать", command=self.edit_source, style='Dark.TButton').pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(toolbar, text="Удалить", command=self.delete_source, style='Dark.TButton').pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(toolbar, text="Обновить", command=self.refresh_sources, style='Dark.TButton').pack(side=tk.LEFT)
        
        list_frame = ttk.Frame(sources_frame, style='Dark.TFrame')
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        columns = ('Название', 'Категория', 'Приоритет', 'URL', 'Статус')
        self.sources_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=15, style='Treeview')
        
        self.sources_tree.heading('Название', text='Название')
        self.sources_tree.heading('Категория', text='Категория')
        self.sources_tree.heading('Приоритет', text='Приоритет')
        self.sources_tree.heading('URL', text='URL')
        self.sources_tree.heading('Статус', text='Статус')
        
        self.sources_tree.column('Название', width=150)
        self.sources_tree.column('Категория', width=100)
        self.sources_tree.column('Приоритет', width=80)
        self.sources_tree.column('URL', width=300)
        self.sources_tree.column('Статус', width=80)
        
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.sources_tree.yview)
        self.sources_tree.configure(yscrollcommand=scrollbar.set)
        
        self.sources_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.sources_tree.bind('<Double-1>', lambda e: self.edit_source())
        
    def create_logs_tab(self, notebook):
        logs_frame = ttk.Frame(notebook, style='Dark.TFrame')
        notebook.add(logs_frame, text="Логи")
        
        logs_toolbar = ttk.Frame(logs_frame, style='Dark.TFrame')
        logs_toolbar.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        ttk.Button(logs_toolbar, text="Очистить логи", command=self.clear_logs, style='Dark.TButton').pack(side=tk.LEFT)
        
        self.logs_text = scrolledtext.ScrolledText(logs_frame, wrap=tk.WORD, bg='#2b2b2b', fg='#ffffff', insertbackground='white')
        self.logs_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        self.setup_logging()
        
    def setup_logging(self):
        class GUIHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget
                
            def emit(self, record):
                msg = self.format(record)
                def append():
                    self.text_widget.insert(tk.END, msg + '\n')
                    self.text_widget.see(tk.END)
                    lines = int(self.text_widget.index('end-1c').split('.')[0])
                    if lines > 1000:
                        self.text_widget.delete('1.0', '100.0')
                self.text_widget.after(0, append)
        
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        
        gui_handler = GUIHandler(self.logs_text)
        gui_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(gui_handler)
        
    def refresh_sources(self):
        for item in self.sources_tree.get_children():
            self.sources_tree.delete(item)
            
        if self.bot:
            for source_name, source_config in self.bot.rss_sources.items():
                status = "Активен" if source_config.get('enabled', True) else "Отключен"
                self.sources_tree.insert('', tk.END, values=(
                    source_name,
                    source_config.get('category', ''),
                    source_config.get('priority', ''),
                    source_config.get('url', ''),
                    status
                ))
                
    def add_source(self):
        dialog = NewsSourceDialog(self.root, "Добавить источник")
        self.root.wait_window(dialog.dialog)
        
        if dialog.result:
            source_name, source_config = dialog.result
            if self.bot:
                self.bot.rss_sources[source_name] = source_config
                self.bot.save_sources()
                self.refresh_sources()
                logging.info(f"Добавлен новый источник: {source_name}")
                
    def edit_source(self):
        selection = self.sources_tree.selection()
        if not selection:
            messagebox.showwarning("Предупреждение", "Выберите источник для редактирования")
            return
            
        item = selection[0]
        source_name = self.sources_tree.item(item)['values'][0]
        
        if self.bot and source_name in self.bot.rss_sources:
            source_data = (source_name, self.bot.rss_sources[source_name])
            dialog = NewsSourceDialog(self.root, f"Редактировать источник: {source_name}", source_data)
            self.root.wait_window(dialog.dialog)
            
            if dialog.result:
                new_name, new_config = dialog.result
                if new_name != source_name:
                    del self.bot.rss_sources[source_name]
                self.bot.rss_sources[new_name] = new_config
                self.bot.save_sources()
                self.refresh_sources()
                logging.info(f"Источник обновлен: {new_name}")
                
    def delete_source(self):
        selection = self.sources_tree.selection()
        if not selection:
            messagebox.showwarning("Предупреждение", "Выберите источник для удаления")
            return
            
        item = selection[0]
        source_name = self.sources_tree.item(item)['values'][0]
        
        if messagebox.askyesno("Подтверждение", f"Удалить источник '{source_name}'?"):
            if self.bot and source_name in self.bot.rss_sources:
                del self.bot.rss_sources[source_name]
                self.bot.save_sources()
                self.refresh_sources()
                logging.info(f"Источник удален: {source_name}")
                
    def clear_logs(self):
        self.logs_text.delete(1.0, tk.END)
        
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.token_var.set(config.get('token', ''))
                    self.chat_id_var.set(config.get('chat_id', ''))
                    self.interval_var.set(config.get('interval', 2))
                    if self.bot:
                        self.bot.filters['whitelist'] = config.get('whitelist', [])
                        self.bot.filters['blacklist'] = config.get('blacklist', [])
                        self.update_filter_listbox('whitelist')
                        self.update_filter_listbox('blacklist')
                logging.info("Конфигурация загружена")
            except Exception as e:
                logging.error(f"Ошибка загрузки конфигурации: {e}")
                messagebox.showerror("Ошибка", f"Не удалось загрузить конфигурацию: {e}")
        
        if self.token_var.get() and self.chat_id_var.get():
            self.bot = RussianMarketNewsBot(self.token_var.get(), self.chat_id_var.get())
            self.update_filter_listbox('whitelist')
            self.update_filter_listbox('blacklist')
            self.refresh_sources()
            
    def save_config(self):
        config = {
            'token': self.token_var.get(),
            'chat_id': self.chat_id_var.get(),
            'interval': self.interval_var.get(),
            'whitelist': self.bot.filters['whitelist'] if self.bot else [],
            'blacklist': self.bot.filters['blacklist'] if self.bot else []
        }
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            if self.bot:
                self.bot.save_filters()
            logging.info("Конфигурация сохранена")
            messagebox.showinfo("Успех", "Конфигурация сохранена")
        except Exception as e:
            logging.error(f"Ошибка сохранения конфигурации: {e}")
            messagebox.showerror("Ошибка", f"Не удалось сохранить конфигурацию: {e}")
            
    def start_monitoring(self):
        token = self.token_var.get().strip()
        chat_id = self.chat_id_var.get().strip()
        
        if not token or not chat_id:
            messagebox.showerror("Ошибка", "Заполните токен бота и ID чата")
            return
            
        try:
            self.bot = RussianMarketNewsBot(token, chat_id)
            self.update_filter_listbox('whitelist')
            self.update_filter_listbox('blacklist')
            self.bot.save_filters()
            self.refresh_sources()
            
            def run_bot():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self.bot.run_monitoring(self.interval_var.get()))
                except Exception as e:
                    logging.error(f"Ошибка в боте: {e}")
                finally:
                    loop.close()
            
            self.bot_thread = threading.Thread(target=run_bot, daemon=True)
            self.bot_thread.start()
            
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.status_var.set("Работает")
            
            logging.info("Мониторинг запущен")
            
        except Exception as e:
            logging.error(f"Ошибка запуска мониторинга: {e}")
            messagebox.showerror("Ошибка", f"Не удалось запустить мониторинг: {e}")
            
    def stop_monitoring(self):
        if self.bot:
            self.bot.stop_monitoring()
            
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_var.set("Остановлен")
        
        logging.info("Мониторинг остановлен")
        
    def on_closing(self):
        if self.bot and self.bot.is_running:
            self.stop_monitoring()
        self.save_config()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = NewsMonitorGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()