# 🛡 NeuroAntiSpam

**Умный Telegram антиспам-бот с ИИ, автообучением и веб-панелью управления.**

---

## ✨ Возможности

| Функция | Описание |
|---|---|
| 🤖 ML + ИИ анализ | Scikit-learn модель + Google Gemini (бесплатно) |
| 🧠 Автообучение | Переобучение каждый час на репортах пользователей |
| 🔐 Капча | Математическое задание для новых участников |
| 🌊 Антифлуд | Мут при быстрых повторных сообщениях |
| 🚨 Защита от рейдов | Кик при массовом вступлении ботов |
| 👻 Теневой бан | Спамер не видит, что его не замечают |
| ⚠️ Система варнов | 3 предупреждения = автобан |
| 🔗 Антиссылки | Блокировка ссылок от новых участников |
| 📊 Статистика | Детальная аналитика в веб-панели |
| 🌐 Веб-панель | Настройка всех групп через сайт |
| 🔑 Telegram OAuth | Вход на сайт через Telegram |
| ⚡ WebSocket | Изменения применяются мгновенно |

---

## 🚀 Деплой за 15 минут

### Шаг 1 — Создай бота в Telegram

1. Открой [@BotFather](https://t.me/BotFather)
2. Отправь `/newbot`
3. Придумай имя: `NeuroAntiSpam`
4. Придумай username: `NeuroAntiSpamBot`
5. **Сохрани токен** — он выглядит так: `7123456789:AAFxxxxxxxxxxxxx`

### Шаг 2 — Создай репозиторий на GitHub

1. Зайди на [github.com](https://github.com) → **New repository**
2. Название: `neuroantispam`
3. Приватный (Private) — рекомендуется
4. Загрузи все файлы этого проекта

### Шаг 3 — Добавь секреты GitHub

Репозиторий → **Settings → Secrets and variables → Actions → New repository secret**

| Секрет | Значение |
|---|---|
| `BOT_TOKEN` | Токен от BotFather |
| `JWT_SECRET` | Любая случайная строка (32+ символа) |
| `API_SECRET_KEY` | Любая случайная строка (32+ символа) |
| `WEBSITE_URL` | URL сайта (после деплоя на Railway) |
| `GEMINI_API_KEY` | Ключ Google Gemini (опционально, бесплатно) |
| `SUPER_ADMINS` | Твой Telegram ID (найди у @userinfobot) |

> **Генератор случайной строки:** открой терминал и введи:
> ```bash
> python3 -c "import secrets; print(secrets.token_hex(32))"
> ```

### Шаг 4 — Деплой сайта на Railway (бесплатно)

1. Зайди на [railway.app](https://railway.app) и войди через GitHub
2. **New Project → Deploy from GitHub repo**
3. Выбери папку `website/`
4. Railway автоматически определит Dockerfile и запустит
5. Зайди в **Settings → Domains → Generate Domain**
6. Скопируй URL и добавь в GitHub secrets как `WEBSITE_URL`

### Шаг 5 — Запусти бота через GitHub Actions

1. В репозитории открой вкладку **Actions**
2. Найди **NeuroAntiSpam Bot**
3. Нажми **Run workflow → Run workflow**
4. Бот запустится и будет работать до 6 часов, затем перезапустится автоматически

### Шаг 6 — Добавь бота в группу

1. Добавь `@NeuroAntiSpamBot` в свою группу
2. Назначь его **администратором**
3. Дай права:
   - ✅ Удаление сообщений
   - ✅ Блокировка участников
   - ✅ Ограничение участников
4. Напиши `/start` — бот активируется

### Шаг 7 — Войди в веб-панель

1. Открой URL сайта (Railway)
2. Нажми **Войти через Telegram**
3. Выбери группу и настрой бота

---

## 🔑 Получить Google Gemini API (бесплатно)

1. Зайди на [aistudio.google.com](https://aistudio.google.com)
2. Нажми **Get API key → Create API key**
3. Скопируй ключ и добавь в GitHub secrets как `GEMINI_API_KEY`

**Бесплатный лимит:** 60 запросов/минуту — более чем достаточно.

---

## 📋 Команды бота

```
/start      — Активировать бота в группе
/help       — Список всех команд
/settings   — Ссылка на веб-панель
/stats      — Статистика группы
/ban        — Заблокировать пользователя (ответом)
/kick       — Удалить из группы (ответом)
/mute [мин] — Заглушить пользователя
/unmute     — Снять мут
/warn       — Предупреждение
/unwarn     — Снять предупреждение
/warns      — Проверить предупреждения
/whitelist  — Добавить в белый список
/blacklist  — Добавить в чёрный список
/addspam    — Добавить спам-фразу
/report     — Пожаловаться на спам (ответом)
/mode       — Режим: soft / medium / hard
/setlang    — Языковой фильтр: ru / en / any
```

---

## 🏗 Структура проекта

```
neuroantispam/
├── bot/
│   ├── main.py              # Главный файл бота
│   ├── config.py            # Конфигурация
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── handlers/
│   │   ├── spam_handler.py  # Обработка спама
│   │   ├── admin_handler.py # Команды администратора
│   │   ├── captcha_handler.py
│   │   ├── member_handler.py
│   │   └── report_handler.py
│   ├── database/
│   │   └── db.py            # База данных (SQLAlchemy)
│   └── ml/
│       └── spam_detector.py # ML + Gemini AI
├── website/
│   ├── api.py               # FastAPI REST + WebSocket
│   ├── index.html           # Веб-панель управления
│   ├── requirements.txt
│   ├── Dockerfile
│   └── railway.toml
├── scripts/
│   └── update_spam_db.py    # Обновление глобальной базы
├── database/
│   └── global_spam_phrases.json
└── .github/
    └── workflows/
        └── bot.yml          # GitHub Actions
```

---

## ❓ Частые вопросы

**Бот не реагирует на спам**
→ Убедись, что у бота есть права администратора с разрешением удалять сообщения.

**Бот блокирует обычные сообщения**
→ Снизь порог чувствительности в настройках (режим `soft` или снизь `spam_threshold` до 85%).

**Сайт не открывается**
→ Подожди 2-3 минуты после деплоя на Railway. Первый запуск занимает время.

**Telegram Login не работает**
→ В файле `index.html` замени `NeuroAntiSpamBot` на точный username твоего бота.

---

## 📄 Лицензия

MIT License — используй свободно.
