#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот для репетитора: ученики, оплаты, занятия, расписание и словарь
с интервальным повторением для учеников.

Переменные окружения:
    TG_BOT_TOKEN    — токен от @BotFather (обязательно)
    TG_OWNER_ID     — ваш Telegram ID, узнать командой /id (желательно)
    TG_BOT_DB       — путь к файлу базы, например /data/tutor.db
    TG_DIGEST_HOUR  — час утренних напоминаний, по умолчанию 9, 0 — выключить
    TG_BACKUP_HOUR  — час ежедневной копии базы в личку, по умолчанию 22, 0 — выключить
    TG_PET_HOUR     — час напоминания про питомца, по умолчанию 18, 0 — выключить

Резервные копии: /backup — прислать файл базы прямо сейчас, /restore — восстановить
(после команды пришлите боту .db-файл). Раз в сутки копия приходит сама.

Зависимостей нет, только стандартная библиотека Python 3.8+.
"""

import csv
import html
import io
import json
import os
import random
import re
import sqlite3
import string
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, time as dtime, timedelta

TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
OWNER_ID = int(os.environ.get("TG_OWNER_ID", "0") or 0)
DIGEST_HOUR = int(os.environ.get("TG_DIGEST_HOUR", "9") or 0)
DB_PATH = os.environ.get("TG_BOT_DB", "tutor_tg.db")
BACKUP_HOUR = int(os.environ.get("TG_BACKUP_HOUR", "22") or 0)  # 0 — выключить
API = "https://api.telegram.org/bot" + TOKEN + "/"
CURRENCY = "₽"
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WD_CAP = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
RATE_PRESETS = [(2000, 60), (1500, 45)]
BOT_NAME = "What's next?"  # как бот называет себя в текстах
PAY_DETAILS = "+7 913 391-77-45 — ВТБ (Алёна П.)"
CANCEL_REASONS = ["по просьбе ученика", "по моей просьбе", "болезнь", "другое"]
KEY_MIN_REVIEWS = 5  # сколько повторений за день нужно для ключика
PET_GOAL = 5         # сколько повторений за день «кормят» питомца
PET_REMIND_HOUR = int(os.environ.get("TG_PET_HOUR", "18") or 0)
FIN_HOUR = int(os.environ.get("TG_FIN_HOUR", "21") or 0)  # вечерний вопрос о тратах
MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
          "сентябрь", "октябрь", "ноябрь", "декабрь")
FIN_CATS = ("Продукты", "Кафе и доставка", "Транспорт", "Здоровье", "Дом и быт",
            "Одежда", "Связь и подписки", "Развлечения", "Подарки", "Образование",
            "Питомцы", "Кредиты", "Прочее")  # 0 — без напоминаний
# Стадии: сколько всего повторений нужно, значок, название
PET_STAGES = [(0, "🥚", "Яйцо"), (30, "🐣", "Птенец"), (120, "🐥", "Цыплёнок"),
              (300, "🦜", "Попугай"), (700, "🦉", "Мудрая сова")]

# --- ИИ для warm-up (необязательно) ---
# AI_FORMAT: "anthropic" для api.anthropic.com, "openai" для любого
# OpenAI-совместимого сервиса (в т.ч. российских прокси и провайдеров).
AI_KEY = os.environ.get("AI_KEY", "").strip()
AI_FORMAT = os.environ.get("AI_FORMAT", "anthropic").strip()
AI_MODEL = os.environ.get("AI_MODEL", "claude-haiku-4-5-20251001").strip()
AI_URL = os.environ.get("AI_URL", "https://api.anthropic.com/v1/messages").strip()
AI_BUDGET = int(os.environ.get("TG_AI_BUDGET", "1000000") or 0)   # всего токенов
AI_DAILY_CAP = int(os.environ.get("TG_AI_DAILY", "40000") or 0)   # потолок в сутки
TEACHER_HANDLE = "alyonapetrowa"
TEACHER_BIO = (
    "Преподаватель английского языка, стаж более пяти лет.\n\n"
    "• МГЛУ им. Мориса Тореза — преподаватель английского и французского\n"
    "• Магистратура МПГУ — проектирование образовательного опыта\n"
    "• Действующий преподаватель грамматики и практики речи "
    "у студентов-лингвистов МПГУ\n\n"
    "Направления: разговорный, деловой и медицинский английский. "
    "Для детей — обучение чтению и помощь со школьной программой.\n\n"
    "Занятия для детей и взрослых, онлайн.")
LEARNED_IVL = 21
NICK_ADJ = ["Быстрый", "Тихий", "Ясный", "Смелый", "Лёгкий", "Дерзкий", "Добрый",
            "Хитрый", "Ловкий", "Яркий", "Северный", "Утренний", "Вечерний", "Звонкий"]
NICK_NOUN = ["Лис", "Филин", "Ёж", "Барс", "Кит", "Сокол", "Бобр", "Олень",
             "Тигр", "Краб", "Ворон", "Хорёк", "Пингвин", "Дельфин"]
KIND_MARK = {"move": " 🔁", "once": " 📌"}
KIND_SHORT = {"move": " п", "once": " р"}
KIND_WORD = {"move": " перенос", "once": " разово"}
WORDS_PER_SESSION = 30

HELP = (
    "👩‍🏫 <b>Учёт занятий, оплат и словаря</b>\n\n"
    "Всё делается кнопками. Быстрые команды:\n"
    "/students — ученики\n"
    "/new Аня — добавить ученика\n"
    "/s Аня — открыть карточку\n"
    "/done — занятие сегодня, /done 15.09 — датой\n"
    "/pay 4 4000 — оплата: 4 занятия, 4000\n"
    "/today — занятия на сегодня со ссылками\n"
    "/ai — расход токенов ИИ\n"
    "/level C2 — ваш уровень для карточек и упражнений\n"
    "/week — расписание на неделю\n"
    "/archive — архив учеников\n"
    "/money — траты, доходы и кредиты\n"
    "/notes — напоминания и заметки\n"
    "/month — итоги месяца\n"
    "/export — выгрузка в CSV\n"
    "/id — ваш Telegram ID"
)


# --------------------------------------------------------------------------- API

def _tg_json(method, params):
    data = json.dumps(params, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API + method, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        try:
            return json.loads(body)
        except Exception:
            return {"ok": False, "description": "HTTP {} {}".format(e.code, body)}
    except Exception as e:
        return {"ok": False, "description": "{}: {}".format(type(e).__name__, e)}


def _tg_form(method, params):
    """Запасной путь: обычная форма вместо JSON — на случай капризов прокси хостинга."""
    flat = {}
    for k, v in params.items():
        if v is None:
            continue
        flat[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
    data = urllib.parse.urlencode(flat).encode("utf-8")
    req = urllib.request.Request(API + method, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        try:
            return json.loads(body)
        except Exception:
            return {"ok": False, "description": "HTTP {} {}".format(e.code, body)}
    except Exception as e:
        return {"ok": False, "description": "{}: {}".format(type(e).__name__, e)}


def tg(method, **params):
    res = _tg_json(method, params)
    if res.get("ok"):
        return res
    res2 = _tg_form(method, params)
    if not res2.get("ok"):
        print("TG FAIL", method, "| json:", res.get("description"),
              "| form:", res2.get("description"))
    return res2 if (res2.get("ok") or res2.get("description")) else res


def send_document(chat_id, filename, content, caption=""):
    boundary = uuid.uuid4().hex
    body = io.BytesIO()

    def field(name, value):
        body.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                    % (boundary, name, value)).encode("utf-8"))

    field("chat_id", str(chat_id))
    if caption:
        field("caption", caption)
    body.write(("--%s\r\nContent-Disposition: form-data; name=\"document\"; filename=\"%s\"\r\n"
                "Content-Type: text/csv\r\n\r\n" % (boundary, filename)).encode("utf-8"))
    body.write(content.encode("utf-8-sig"))
    body.write(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    req = urllib.request.Request(API + "sendDocument", data=body.getvalue(), method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print("sendDocument error:", e)
        return {}


def send_bytes(chat_id, filename, data, caption="", mime="application/octet-stream"):
    """Отправка бинарного файла (например, базы) как документа."""
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    body.write(("--%s\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n%s\r\n"
                % (boundary, chat_id)).encode("utf-8"))
    if caption:
        body.write(("--%s\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n%s\r\n"
                    % (boundary, caption)).encode("utf-8"))
    body.write(("--%s\r\nContent-Disposition: form-data; name=\"document\"; filename=\"%s\"\r\n"
                "Content-Type: %s\r\n\r\n" % (boundary, filename, mime)).encode("utf-8"))
    body.write(data)
    body.write(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    req = urllib.request.Request(API + "sendDocument", data=body.getvalue(), method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print("sendDocument error:", e)
        return {"ok": False, "description": "{}: {}".format(type(e).__name__, e)}


def download_file(file_id):
    """Скачивает файл, присланный в Telegram, и возвращает его байты."""
    info = tg("getFile", file_id=file_id)
    path = (info.get("result") or {}).get("file_path")
    if not path:
        return None
    url = "https://api.telegram.org/file/bot{}/{}".format(TOKEN, path)
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def button(text, data):
    if data.startswith(("http://", "https://", "tg://")):
        return {"text": text, "url": data}
    return {"text": text, "callback_data": data}


def markup(rows):
    if not rows:
        return None
    return {"inline_keyboard": [[button(t, d) for t, d in row] for row in rows]}


def strip_html(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text or ""))


def split_text(text, limit=3500):
    """Режет длинный текст по строкам, чтобы уложиться в лимит Telegram."""
    out, cur, size = [], [], 0
    for line in text.split("\n"):
        chunks = ([line[i:i + limit] for i in range(0, len(line), limit)]
                  if len(line) > limit else [line])
        for ch in chunks:
            if size + len(ch) + 1 > limit and cur:
                out.append("\n".join(cur))
                cur, size = [], 0
            cur.append(ch)
            size += len(ch) + 1
    if cur:
        out.append("\n".join(cur))
    return out or [""]


def send(chat_id, text, rows=None):
    """Отправка с подстраховкой: если Telegram не принял разметку — шлём простым текстом."""
    if len(text) > 4000:
        parts = split_text(text)
        res = None
        for i, part in enumerate(parts):
            res = send_one(chat_id, part, rows if i == len(parts) - 1 else None)
        return res
    return send_one(chat_id, text, rows)


def send_one(chat_id, text, rows=None, temp=False):
    if not temp:
        clear_temp(chat_id)
    res = tg("sendMessage", chat_id=chat_id, text=text[:4000], parse_mode="HTML",
             reply_markup=markup(rows), disable_web_page_preview=True)
    if res.get("ok"):
        return res
    plain = strip_html(text)[:4000]
    res2 = tg("sendMessage", chat_id=chat_id, text=plain,
              reply_markup=markup(rows), disable_web_page_preview=True)
    if not res2.get("ok"):
        print("sendMessage failed:", res.get("description"), "|",
              res2.get("description"), "| text:", plain[:80])
    return res2


def edit(chat_id, message_id, text, rows=None):
    res = tg("editMessageText", chat_id=chat_id, message_id=message_id, text=text[:4000],
             parse_mode="HTML", reply_markup=markup(rows), disable_web_page_preview=True)
    if not res.get("ok"):
        return send(chat_id, text, rows)
    return res


def delete_message(chat_id, message_id):
    if message_id:
        tg("deleteMessage", chat_id=chat_id, message_id=message_id)


TEMP_MSG = {}


def send_temp(chat_id, text):
    """Сообщение «подождите»: исчезнет, как только придёт настоящий ответ."""
    res = send_one(chat_id, text, temp=True)
    mid = ((res or {}).get("result") or {}).get("message_id")
    if mid:
        TEMP_MSG.setdefault(chat_id, []).append(mid)
    return res


def clear_temp(chat_id):
    for mid in TEMP_MSG.pop(chat_id, []):
        try:
            delete_message(chat_id, mid)
        except Exception:
            pass


def flash(chat_id, text, rows=None):
    """Служебное сообщение: предыдущее такое же удаляется, чтобы чат не зарастал."""
    key = "flash:%s" % chat_id
    old = meta_get(key)
    if old:
        try:
            delete_message(chat_id, int(old))
        except Exception:
            pass
    res = send(chat_id, text, rows)
    mid = (res.get("result") or {}).get("message_id")
    meta_set(key, mid or "")
    return res


def clear_flash(chat_id):
    key = "flash:%s" % chat_id
    old = meta_get(key)
    if old:
        try:
            delete_message(chat_id, int(old))
        except Exception:
            pass
        meta_set(key, "")


def toast(cq_id, text=""):
    tg("answerCallbackQuery", callback_query_id=cq_id, text=text[:190])


def esc(s):
    return html.escape(str(s or ""))


def pre(text):
    return "<pre>" + esc(text) + "</pre>"


# ------------------------------------------------------------------------- База

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER, name TEXT, rate REAL DEFAULT 0, archived INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, lessons INTEGER, amount REAL, paid_on TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, held_on TEXT, note TEXT,
    kind TEXT DEFAULT 'held', charged INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, weekday INTEGER, at TEXT);
CREATE TABLE IF NOT EXISTS moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, from_date TEXT, to_date TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS appts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, on_date TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, term TEXT, translation TEXT, added_by TEXT,
    due TEXT, ivl INTEGER DEFAULT 0, ease REAL DEFAULT 2.5,
    reps INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS homework (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, text TEXT, due TEXT, created TEXT, done INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, kind TEXT, title TEXT, ref TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, side TEXT, rating INTEGER, text TEXT, anon INTEGER, created TEXT);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, on_date TEXT, word_id INTEGER, grade INTEGER);
CREATE TABLE IF NOT EXISTS state (
    chat_id INTEGER PRIMARY KEY, student_id INTEGER, pending TEXT);
CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    on_date TEXT, ts TEXT, student_id INTEGER, kind TEXT,
    in_tok INTEGER DEFAULT 0, out_tok INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ex_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    on_date TEXT, student_id INTEGER, kind TEXT,
    tasks TEXT, answers TEXT, feedback TEXT);
CREATE TABLE IF NOT EXISTS fin_tx (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    on_date TEXT, kind TEXT, amount REAL, title TEXT, category TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS fin_cat (merchant TEXT PRIMARY KEY, category TEXT);
CREATE TABLE IF NOT EXISTS credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, balance REAL, rate REAL, min_pay REAL, fee REAL DEFAULT 0,
    pay_day INTEGER, closed INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER, text TEXT, file_id TEXT, file_kind TEXT, file_name TEXT,
    due TEXT, repeat TEXT, done INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS hw_draft (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER, book TEXT, code TEXT, text TEXT, audio TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS books (
    id TEXT PRIMARY KEY, data TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS audio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book TEXT, code TEXT, track TEXT, file_id TEXT, kind TEXT, name TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS materials_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book TEXT, code TEXT, kind TEXT, body TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""

MIGRATIONS = [
    ("students", "duration", "INTEGER DEFAULT 60"),
    ("students", "tg_user_id", "INTEGER"),
    ("students", "code", "TEXT"),
    ("students", "code_kid", "TEXT"),
    ("students", "access", "TEXT DEFAULT 'full'"),
    ("students", "nick", "TEXT"),
    ("words", "seen", "TEXT"),
    ("students", "is_self", "INTEGER DEFAULT 0"),
    ("students", "is_guest", "INTEGER DEFAULT 0"),
    ("students", "zoom", "TEXT"),
    ("students", "pet_name", "TEXT"),
    ("words", "ipa", "TEXT"),
    ("words", "definition", "TEXT"),
    ("words", "syn", "TEXT"),
    ("words", "ant", "TEXT"),
    ("words", "coll", "TEXT"),
    ("words", "example", "TEXT"),
    ("students", "level", "TEXT"),
    ("students", "quiet", "INTEGER DEFAULT 0"),
    ("students", "book", "TEXT"),
    ("students", "unit", "INTEGER"),
    ("students", "lesson", "INTEGER"),
    ("audio", "uid", "TEXT"),
    ("audio", "task", "TEXT"),
    ("audio", "answers", "TEXT"),
    ("audio", "sort", "INTEGER"),
    ("students", "keys", "INTEGER DEFAULT 0"),
    ("lessons", "reason", "TEXT"),
    ("payments", "receipt", "TEXT"),
    ("words", "raw", "INTEGER DEFAULT 0"),
]


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, col, decl in MIGRATIONS:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(%s)" % table)]
        if col not in cols:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))
    return conn


def q(sql, args=(), one=False):
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows


def run(sql, args=()):
    with db() as conn:
        return conn.execute(sql, args).lastrowid


def meta_get(k, default=None):
    row = q("SELECT v FROM meta WHERE k=?", (k,), one=True)
    return row["v"] if row else default


def meta_set(k, v):
    run("INSERT INTO meta (k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def get_state(chat_id):
    row = q("SELECT * FROM state WHERE chat_id=?", (chat_id,), one=True)
    if not row:
        return {"student_id": None, "pending": None}
    return {"student_id": row["student_id"],
            "pending": json.loads(row["pending"]) if row["pending"] else None}


def set_state(chat_id, student_id=..., pending=...):
    st = get_state(chat_id)
    if student_id is not ...:
        st["student_id"] = student_id
    if pending is not ...:
        st["pending"] = pending
    run("""INSERT INTO state (chat_id, student_id, pending) VALUES (?,?,?)
           ON CONFLICT(chat_id) DO UPDATE SET student_id=excluded.student_id,
                                              pending=excluded.pending""",
        (chat_id, st["student_id"],
         json.dumps(st["pending"], ensure_ascii=False) if st["pending"] else None))


def students(chat_id, archived=False):
    return q("SELECT * FROM students WHERE chat_id=? AND archived=? "
             "AND COALESCE(is_self,0)=0 AND COALESCE(is_guest,0)=0 ORDER BY name",
             (chat_id, 1 if archived else 0))


def guests(chat_id):
    return q("SELECT * FROM students WHERE chat_id=? AND COALESCE(is_guest,0)=1 ORDER BY id",
             (chat_id,))


def owner_home():
    """Чат преподавателя — к нему привязываем гостей."""
    return int(meta_get("owner_chat", OWNER_ID or 0) or 0)


def make_guest(user_id, title=None):
    home = owner_home()
    existing = student_by_user(user_id)
    if existing:
        return existing
    nick = gen_nick(home)
    sid = run("INSERT INTO students (chat_id, name, nick, is_guest, tg_user_id, access) "
              "VALUES (?,?,?,1,?,'kid')", (home, nick, nick, user_id))
    return student(sid)


def self_student(chat_id, user_id=None):
    """Карточка самого преподавателя — чтобы учить слова и быть в рейтинге."""
    row = q("SELECT * FROM students WHERE chat_id=? AND is_self=1", (chat_id,), one=True)
    if row:
        return row
    sid = run("INSERT INTO students (chat_id, name, nick, is_self, tg_user_id, access) "
              "VALUES (?,?,?,1,?,'full')",
              (chat_id, "Я", "Я", user_id or chat_id))
    return student(sid)


def learners(chat_id):
    rows = list(students(chat_id))
    me = q("SELECT * FROM students WHERE chat_id=? AND is_self=1", (chat_id,), one=True)
    if me:
        rows.append(me)
    rows += list(guests(chat_id))
    return rows


BLANK_STUDENT = {"id": 0, "chat_id": None, "name": "—", "rate": 0, "duration": 60,
                 "archived": 0, "tg_user_id": None, "code": None, "code_kid": None,
                 "access": "full", "nick": None}


def student(sid):
    return q("SELECT * FROM students WHERE id=?", (sid,), one=True)


def sget(sid):
    """Как student(), но никогда не возвращает None — бот не падает на старых кнопках."""
    return student(sid) or dict(BLANK_STUDENT)


def student_by_user(user_id):
    return q("SELECT * FROM students WHERE tg_user_id=?", (user_id,), one=True)


def owner_chat(sid):
    s = sget(sid)
    return s["chat_id"] if s else None


def stats(sid):
    p = q("SELECT COALESCE(SUM(lessons),0) l, COALESCE(SUM(amount),0) a "
          "FROM payments WHERE student_id=?", (sid,), one=True)
    held = q("SELECT COUNT(*) c FROM lessons WHERE student_id=? AND charged=1", (sid,), one=True)["c"]
    free = q("SELECT COUNT(*) c FROM lessons WHERE student_id=? AND charged=0", (sid,), one=True)["c"]
    return {"paid_lessons": p["l"], "paid_amount": p["a"], "held": held,
            "free": free, "left": p["l"] - held}


# ----------------------------------------------------------------------- Утилиты

def today():
    return date.today()


def fmt_date(d, short=False):
    if isinstance(d, str):
        d = datetime.strptime(d, "%Y-%m-%d").date()
    return d.strftime("%d.%m" if short else "%d.%m.%Y")


def parse_date(text):
    t = (text or "").strip().lower()
    if t in ("сегодня", "today", ""):
        return today()
    if t in ("вчера", "yesterday"):
        return today() - timedelta(days=1)
    if t in ("завтра", "tomorrow"):
        return today() + timedelta(days=1)
    m = re.fullmatch(r"(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?", t)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
    year = today().year if not y else (2000 + int(y) if len(y) == 2 else int(y))
    try:
        return date(year, mo, d)
    except ValueError:
        return None


def parse_date_time(text):
    t = (text or "").strip().lower()
    tm = re.search(r"(\d{1,2})[:.](\d{2})\s*$", t) or re.search(r"\s(\d{1,2})[:.](\d{2})", t)
    at = None
    if tm:
        at = "{:02d}:{}".format(int(tm.group(1)), tm.group(2))
        t = (t[:tm.start()] + " " + t[tm.end():]).strip()
    return parse_date(t.strip()), at


def plural(n, forms=("занятие", "занятия", "занятий")):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def fmt_money(x):
    return "{:,.0f}".format(x or 0).replace(",", " ") + " " + CURRENCY


def rate_text(s):
    if not s["rate"]:
        return ""
    return "{} / {} мин".format(fmt_money(s["rate"]), s["duration"] or 60)


def parse_slots(text):
    out = []
    for part in re.split(r"[,;]+", text.strip().lower()):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"([а-я]{2,3})\.?\s*(\d{1,2}[:.]\d{2})?", part)
        if not m:
            continue
        day = m.group(1)[:2]
        if day not in WEEKDAYS:
            continue
        at = (m.group(2) or "").replace(".", ":")
        if at and len(at.split(":")[0]) == 1:
            at = "0" + at
        out.append((WEEKDAYS.index(day), at))
    return out


def slots_text(sid):
    cur = q("SELECT weekday, at FROM slots WHERE student_id=? ORDER BY weekday, at", (sid,))
    return ", ".join("{} {}".format(WEEKDAYS[x["weekday"]], x["at"]).strip() for x in cur)


def parse_dates(text):
    """'22.09 17:00, 25.09 12:00' -> [(date, 'HH:MM'), ...]"""
    out = []
    for part in re.split(r"[,;\n]+", text):
        part = part.strip()
        if not part:
            continue
        d, at = parse_date_time(part)
        if d:
            out.append((d, at or ""))
    return out


def occurrences(sid, count, start=None):
    """Ближайшие занятия: список (дата, 'ЧЧ:ММ', вид), вид: '' | 'move' | 'once'."""
    slots = q("SELECT weekday, at FROM slots WHERE student_id=? ORDER BY weekday, at", (sid,))
    start = start or today()
    mv = q("SELECT * FROM moves WHERE student_id=?", (sid,))
    skip = {m["from_date"] for m in mv}
    out = [(datetime.strptime(m["to_date"], "%Y-%m-%d").date(), m["at"] or "", "move")
           for m in mv if m["to_date"] >= start.isoformat()]
    out += [(datetime.strptime(a["on_date"], "%Y-%m-%d").date(), a["at"] or "", "once")
            for a in q("SELECT * FROM appts WHERE student_id=? AND on_date>=? ORDER BY on_date",
                       (sid, start.isoformat()))]
    if slots:
        cur, days = start, 0
        while len(out) < count + 10 and days < 400:
            if cur.isoformat() not in skip:
                for s in slots:
                    if s["weekday"] == cur.weekday():
                        out.append((cur, s["at"] or "", ""))
            cur += timedelta(days=1)
            days += 1
    out = [o for o in out if o[0] >= start]
    out.sort(key=lambda x: (x[0], x[1]))
    return out[:count]


# --------------------------------------------------------- Интервальное повторение

def due_words(sid, limit=WORDS_PER_SESSION):
    return q("SELECT * FROM words WHERE student_id=? AND due<=? AND COALESCE(raw,0)=0 "
             "ORDER BY due, COALESCE(seen,''), id LIMIT ?",
             (sid, today().isoformat(), limit))


def raw_words(sid):
    return q("SELECT * FROM words WHERE student_id=? AND raw=1 ORDER BY id", (sid,))


def due_count(sid):
    return q("SELECT COUNT(*) c FROM words WHERE student_id=? AND due<=? AND COALESCE(raw,0)=0",
             (sid, today().isoformat()), one=True)["c"]


def word_count(sid):
    return q("SELECT COUNT(*) c FROM words WHERE student_id=? AND COALESCE(raw,0)=0",
             (sid,), one=True)["c"]


def last_batch(sid, limit=12):
    """Последний список слов, добавленный преподавателем."""
    row = q("SELECT MAX(created) d FROM words WHERE student_id=? AND added_by='педагог' "
            "AND COALESCE(raw,0)=0", (sid,), one=True)
    if not row or not row["d"]:
        return []
    return q("SELECT * FROM words WHERE student_id=? AND created=? AND COALESCE(raw,0)=0 "
             "ORDER BY id LIMIT ?", (sid, row["d"], limit))


def sm2(ease, ivl, reps, lapses, grade):
    """Anki-подобный шаг: 0 — Again, 1 — Hard, 2 — Good, 3 — Easy."""
    ease, ivl, reps, lapses = ease or 2.5, ivl or 0, reps or 0, lapses or 0
    if grade == 0:
        return max(1.3, ease - 0.2), 0, reps, lapses + 1
    if grade == 1:
        return (max(1.3, ease - 0.15),
                1 if reps == 0 else max(1, int(round(ivl * 1.2))), reps + 1, lapses)
    if grade == 2:
        return ease, 1 if reps == 0 else max(1, int(round(ivl * ease))), reps + 1, lapses
    return (min(3.0, ease + 0.15),
            4 if reps == 0 else max(2, int(round(ivl * ease * 1.3))), reps + 1, lapses)


def preview_ivl(w, grade):
    """Через сколько дней слово вернётся при такой оценке (0 — сегодня)."""
    return sm2(w["ease"], w["ivl"], w["reps"], w["lapses"], grade)[1]


def ivl_label(days):
    if not days:
        return "сегодня"
    if days < 30:
        return "{}д".format(days)
    if days < 365:
        return "{}мес".format(max(1, round(days / 30)))
    return "{}г".format(round(days / 365, 1))


def grade_word(word_id, grade):
    """grade: 0 Again, 1 Hard, 2 Good, 3 Easy."""
    w = q("SELECT * FROM words WHERE id=?", (word_id,), one=True)
    if not w:
        return None
    ease, ivl, reps, lapses = sm2(w["ease"], w["ivl"], w["reps"], w["lapses"], grade)
    due = (today() + timedelta(days=ivl)).isoformat()
    run("UPDATE words SET ease=?, ivl=?, reps=?, lapses=?, due=?, seen=? WHERE id=?",
        (ease, ivl, reps, lapses, due, datetime.now().isoformat(timespec="seconds"), word_id))
    run("INSERT INTO reviews (student_id, on_date, word_id, grade) VALUES (?,?,?,?)",
        (w["student_id"], today().isoformat(), word_id, grade))
    return ivl


def progress(sid):
    total = word_count(sid)
    learned = q("SELECT COUNT(*) c FROM words WHERE student_id=? AND ivl>=?",
                (sid, LEARNED_IVL), one=True)["c"]
    started = q("SELECT COUNT(*) c FROM words WHERE student_id=? AND reps>0 AND ivl<?",
                (sid, LEARNED_IVL), one=True)["c"]
    fresh = q("SELECT COUNT(*) c FROM words WHERE student_id=? AND reps=0", (sid,), one=True)["c"]
    week = (today() - timedelta(days=6)).isoformat()
    month = (today() - timedelta(days=29)).isoformat()
    rev7 = q("SELECT COUNT(*) c FROM reviews WHERE student_id=? AND on_date>=?",
             (sid, week), one=True)["c"]
    days30 = [r["on_date"] for r in
              q("SELECT DISTINCT on_date FROM reviews WHERE student_id=? AND on_date>=? "
                "ORDER BY on_date DESC", (sid, month))]
    acc = q("SELECT COUNT(*) c, SUM(CASE WHEN grade>0 THEN 1 ELSE 0 END) ok "
            "FROM reviews WHERE student_id=? AND on_date>=?", (sid, month), one=True)
    streak, day = 0, today()
    dayset = set(days30)
    if today().isoformat() not in dayset and (today() - timedelta(days=1)).isoformat() in dayset:
        day = today() - timedelta(days=1)
    while day.isoformat() in dayset:
        streak += 1
        day -= timedelta(days=1)
    last = q("SELECT MAX(on_date) d FROM reviews WHERE student_id=?", (sid,), one=True)["d"]
    return {"total": total, "learned": learned, "started": started, "new": fresh,
            "pct": round(learned * 100 / total) if total else 0,
            "rev7": rev7, "days30": len(days30), "streak": streak,
            "acc": round((acc["ok"] or 0) * 100 / acc["c"]) if acc["c"] else 0,
            "last": last, "due": due_count(sid)}


def current_hw(sid):
    return q("SELECT * FROM homework WHERE student_id=? AND done=0 ORDER BY id DESC LIMIT 1",
             (sid,), one=True)


def materials_of(sid):
    return q("SELECT * FROM materials WHERE student_id IN (?, 0) ORDER BY student_id DESC, id DESC",
             (sid,))


def upcoming(sid, count=1):
    """Ближайшие занятия без сегодняшнего, если оно уже отмечено проведённым."""
    occ = occurrences(sid, count + 3)
    if q("SELECT 1 FROM lessons WHERE student_id=? AND held_on=? LIMIT 1",
         (sid, today().isoformat()), one=True):
        occ = [o for o in occ if o[0] != today()]
    return occ[:count]


def next_lesson_date(sid):
    occ = upcoming(sid, 1)
    return occ[0][0] if occ else None


def send_file(chat_id, file_id, caption=""):
    return tg("sendDocument", chat_id=chat_id, document=file_id, caption=caption[:200])


def level_of(sid):
    """Уровень для заданий: заданный вручную, иначе C2 для своего словаря."""
    s_ = sget(sid)
    return s_["level"] or ("C2" if s_["is_self"] else "A2-B1")


def zoom_link(s):
    z = (s["zoom"] or "").strip()
    return z if z.startswith("http") else ""


def zoom_rows(s):
    """Кнопка подключения — у каждого ученика своя ссылка."""
    z = zoom_link(s)
    return [[("🎥 Подключиться к занятию", z)]] if z else []


def announce_material(sid, title, url, for_all=False):
    """Сообщает ученику (или всем, если материал общий), что появился материал."""
    rows = [[("🌐 Открыть", url)]] if url.startswith("http") else None
    body = "📎 <b>Новый материал</b>\n{}".format(esc(title))
    if for_all:
        for s in q("SELECT * FROM students WHERE tg_user_id IS NOT NULL AND archived=0 "
                   "AND COALESCE(is_guest,0)=0 AND COALESCE(is_self,0)=0"):
            send(s["tg_user_id"], body, rows)
        return
    return notify_student(sid, body, rows)


def notify_student(sid, text, rows=None):
    s = sget(sid)
    if s["tg_user_id"]:
        send(s["tg_user_id"], text, rows)
        return True
    return False


def gen_nick(chat_id):
    used = {x["nick"] for x in learners(chat_id) if x["nick"]}
    for _ in range(60):
        nick = "{} {}".format(random.choice(NICK_ADJ), random.choice(NICK_NOUN))
        if nick not in used:
            return nick
    return "Гость {}".format(random.randint(100, 999))


def nick_of(s):
    return s["nick"] or "Ученик {}".format(s["id"])


def leaderboard(chat_id, me_sid=None, real_names=False):
    rows = []
    for s in learners(chat_id):
        p = progress(s["id"])
        if not p["total"]:
            continue
        name = s["name"] if real_names else nick_of(s)
        rows.append((p["learned"], p["rev7"], name, p, s["id"]))
    rows.sort(reverse=True)
    if not rows:
        return "Пока никто не начал заниматься словами."
    out = ["{:<14}{:>5}{:>6}{:>6}".format("Кто", "выуч", "%", "7дн")]
    for learned, rev7, name, p, sid in rows[:15]:
        mark = "→" if sid == me_sid else " "
        out.append("{}{:<13}{:>5}{:>6}{:>6}".format(mark, name[:13], learned, p["pct"], rev7))
    return pre("\n".join(out))


def looks_like_wordlist(text):
    """Похоже ли сообщение на список слов или выражений, а не на фразу или заметку."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if len(lines) < 2 or len(lines) > 40:
        return False
    for l in lines:
        if len(l) > 70 or l.startswith("/"):
            return False
        body = l.split(" - ")[0].split(" — ")[0].split(" = ")[0].strip()
        if len(body.split()) > 5 or body.endswith((".", "!", "?", ":")):
            return False
    return True


def parse_words(text):
    """Строки вида 'word - перевод'. Разделители: - – — = : таб, двойной пробел."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.split(r"\s+[-–—=:]\s+|\t+|\s{2,}", line, maxsplit=1)
        if len(m) < 2:
            m = re.split(r"[-–—=:]", line, maxsplit=1)
        if len(m) < 2:
            continue
        term, tr = m[0].strip()[:100], m[1].strip()[:150]
        if term and tr:
            out.append((term, tr))
    return out[:200]


def add_words(sid, pairs, added_by):
    for term, tr in pairs:
        run("""INSERT INTO words (student_id, term, translation, added_by, due, created)
               VALUES (?,?,?,?,?,?)""",
            (sid, term, tr, added_by, today().isoformat(), today().isoformat()))
    return len(pairs)


# --------------------------------------------------------------- Экраны педагога

def screen_students(chat_id):
    rows, line = [], []
    for s in students(chat_id):
        st = stats(s["id"])
        mark = "⚠️" if st["left"] <= 0 else ("🔸" if st["left"] == 1 else "")
        line.append(("{}{} · {}".format(mark, s["name"], st["left"]), "st:%d" % s["id"]))
        if len(line) == 2:
            rows.append(line)
            line = []
    if line:
        rows.append(line)
    rows.append([("➕ Ученик", "new"), ("📊 Месяц", "month")])
    rows.append([("📚 Мой словарь", "myw"), ("📕 Учебники", "books")])
    rows.append([("💰 Деньги", "money")])
    rows.append([("⏰ Напоминания", "notes"), ("💌 Визитка", "promo_me")])
    rows.append([("📁 CSV", "export")])
    text = ("👩‍🏫 <b>Ученики</b>\nРядом с именем — остаток оплаченных занятий.\n"
            "⚠️ оплата закончилась · 🔸 остался один урок")
    if not students(chat_id):
        text = "Учеников пока нет. Добавьте первого 👇"
    return text, rows


def screen_student(sid):
    s = sget(sid)
    st = stats(sid)
    last = q("SELECT * FROM lessons WHERE student_id=? ORDER BY held_on DESC, id DESC LIMIT 1",
             (sid,), one=True)
    lastpay = q("SELECT * FROM payments WHERE student_id=? ORDER BY id DESC LIMIT 1", (sid,), one=True)

    lines = ["👤 <b>{}</b>".format(esc(s["name"])), ""]
    lines.append("Проведено: <b>{}</b>".format(st["held"]))
    lines.append("Оплачено занятий: <b>{}</b>".format(st["paid_lessons"]))
    if st["left"] >= 0:
        lines.append("Остаток: <b>{}</b> {}".format(st["left"], "✅" if st["left"] else "⚠️"))
    else:
        debt = -st["left"]
        extra = " (≈ {})".format(fmt_money(debt * s["rate"])) if s["rate"] else ""
        lines.append("Долг: <b>{} {}</b>{} ⚠️".format(debt, plural(debt), extra))
    if st["free"]:
        lines.append("Без списания: {}".format(st["free"]))
    lines.append("Оплат всего: {}".format(fmt_money(st["paid_amount"])))
    if s["rate"]:
        lines.append("Ставка: {}".format(rate_text(s)))
    if last:
        tag = "" if last["kind"] == "held" else " (отмена)"
        note = " — " + esc(last["note"]) if last["note"] else ""
        lines.append("Последнее: {}{}{}".format(fmt_date(last["held_on"]), tag, note))
    if lastpay:
        lines.append("Последняя оплата: {} за {} зан. — {}".format(
            fmt_money(lastpay["amount"]), lastpay["lessons"], fmt_date(lastpay["paid_on"])))
    sl = slots_text(sid)
    nap = q("SELECT COUNT(*) c FROM appts WHERE student_id=? AND on_date>=?",
            (sid, today().isoformat()), one=True)["c"]
    lines.append("Расписание: " + (sl if sl else
                                   ("разовые даты ({})".format(nap) if nap else "не задано")))
    occ = upcoming(sid, max(st["left"], 3))
    if occ:
        lines.append("Ближайшие: " + ", ".join(
            "{} {}{}".format(fmt_date(d, True), t, KIND_MARK.get(k, "")).strip()
            for d, t, k in occ[:3]))
        if st["left"] > 0 and len(occ) >= st["left"]:
            lines.append("Оплаченных хватит до <b>{}</b>".format(fmt_date(occ[st["left"] - 1][0])))
    total = word_count(sid)
    if total:
        lines.append("Словарь: {} слов, на сегодня {}".format(total, due_count(sid)))
    if zoom_link(s):
        lines.append('🎥 <a href="{}">Ссылка на занятие</a>'.format(esc(zoom_link(s))))
    elif s["zoom"]:
        lines.append("Zoom: {}".format(esc(s["zoom"])))
    hw = current_hw(sid)
    if hw:
        lines.append("Домашка: {}".format(esc(hw["text"][:60])))
    if s["keys"]:
        lines.append("Ключиков у ученика: {}".format(s["keys"]))
    if s["tg_user_id"]:
        lines.append("Ученик подключён к боту ✅")

    if book_of(sid):
        lines.append("📕 {}".format(esc(lesson_label(sid))))
    rows = [
        [("✅ Провела", "done:%d" % sid), ("💰 Оплата", "pay:%d" % sid)],
        [("📕 {}".format(lesson_label(sid).split(" · ")[-1][:26] if book_of(sid)
                         else "Учебник"), "book:%d" % sid)],
        [("🔥 Warm-up", "warm:%d" % sid), ("📝 Домашка", "hw:%d" % sid)],
        [("🗓 Занятия", "schedm:%d" % sid), ("📚 Учёба", "studym:%d" % sid)],
        [("📤 Ученику", "share:%d" % sid), ("⚙️ Ещё", "more:%d" % sid)],
        [("⬅️ К ученикам", "menu")],
    ]
    return "\n".join(lines), rows


def screen_sched_menu(sid):
    st = stats(sid)
    occ = upcoming(sid, 3)
    lines = ["🗓 <b>Занятия — {}</b>".format(esc(sget(sid)["name"])), "",
             "Расписание: " + (slots_text(sid) or "не задано"),
             "Остаток оплаченных: <b>{}</b>".format(max(st["left"], 0))]
    if occ:
        lines.append("Ближайшие: " + ", ".join(
            "{} {}".format(fmt_date(d, True), t).strip() for d, t, _ in occ))
    return "\n".join(lines), [
        [("✅ Провела", "done:%d" % sid), ("📅 Другой датой", "doned:%d" % sid)],
        [("🚫 Отмена урока", "cancel:%d" % sid), ("🔁 Перенести", "move:%d" % sid)],
        [("🗓 Постоянное расписание", "sched:%d" % sid)],
        [("📋 История", "hist:%d" % sid)],
        [("⬅️ Назад", "st:%d" % sid)]]


def screen_study_menu(sid):
    p = progress(sid)
    lines = ["📚 <b>Учёба — {}</b>".format(esc(sget(sid)["name"])), "",
             "Слов: <b>{}</b> · выучено: <b>{}</b> ({}%)".format(
                 p["total"], p["learned"], p["pct"]),
             "На сегодня: <b>{}</b> · дней подряд: <b>{}</b>".format(p["due"], p["streak"])]
    hw = current_hw(sid)
    if hw:
        lines.append("Домашка: {}".format(esc(hw["text"][:60])))
    return "\n".join(lines), [
        [("📚 Слова", "words:%d" % sid), ("📎 Материалы", "mat:%d" % sid)],
        [("📝 Домашка", "hw:%d" % sid), ("🔥 Warm-up", "warm:%d" % sid)],
        [("📊 Сводка за неделю", "report:%d" % sid)],
        [("📈 Прогресс", "prog:%d" % sid), ("📊 Статистика", "lrn_stats:%d" % sid)],
        [("💬 Отзывы", "fb:%d" % sid)],
        [("⬅️ Назад", "st:%d" % sid)]]


def audio_match(book, name):
    """По имени файла определяет источник (PB/WB), номер трека и урок."""
    n = " " + re.sub(r"[_\-]+", " ", name or "").lower() + " "
    n = re.sub(r"\b(l|lvl|level)\s?\d\b", " ", n)          # L4 — это уровень, не урок
    n = re.sub(r"\b(cd|disc|disk)\s?\d\b", " ", n)
    source = ""
    if re.search(r"\bwb\b|workbook|activity|рабочая", n):
        source = "WB"
    elif re.search(r"\bpb\b|pupil|\bsb\b|student", n):
        source = "PB"
    elif re.search(r"\btb\b|teacher", n):
        source = "TB"
    # номер трека: 8.11, 1.08 — вторая часть из двух цифр
    track = ""
    mt = re.search(r"\b(\d{1,2})\.(\d{2})\b", n)
    if mt:
        track = "{}.{}".format(mt.group(1), mt.group(2))
        n = n.replace(mt.group(0), " ")
    code = None
    # урок по номеру трека из книги учителя
    has_map = any(l.get("tracks") for u in book["units"] for l in u["lessons"])
    if track:
        for u in book["units"]:
            for l in u["lessons"]:
                if track in (l.get("tracks") or []):
                    code = l["code"]
        if not code and not has_map:
            # в детских курсах номер трека — это «юнит.номер»
            un_ = int(track.split(".")[0])
            if unit_of(book, un_):
                code = "{}.1".format(un_)
    # явный код урока: 3.2, unit 3 lesson 2, u3l2
    if not code:
        m = re.search(r"\b(\d{1,2})\s?[.．]\s?(\d)\b(?!\d)", n)
        if m and lesson_of(book, int(m.group(1)), int(m.group(2))):
            code = "{}.{}".format(int(m.group(1)), int(m.group(2)))
    if not code:
        m2 = re.search(r"\bu(?:nit)?\s*(\d{1,2}).{0,12}?\bl(?:esson)?\s*(\d{1,2})\b", n)
        if m2 and lesson_of(book, int(m2.group(1)), int(m2.group(2))):
            code = "{}.{}".format(int(m2.group(1)), int(m2.group(2)))
    # только юнит — вешаем на первый урок юнита
    if not code:
        m3 = re.search(r"\bu(?:nit)?\s*(\d{1,2})\b", n)
        if m3 and unit_of(book, int(m3.group(1))):
            code = "{}.1".format(int(m3.group(1)))
    return code, track, source


def audio_store(book, name, file_id, code=None, source="", track="", uid=""):
    """Кладёт трек, не создавая дублей: один и тот же файл не запишется дважды."""
    dup = q("SELECT id FROM audio WHERE book=? AND (file_id=? OR (uid<>'' AND uid=?) "
            "OR (name=? AND COALESCE(track,'')=?))",
            (book["id"], file_id, uid or "\u0000", name[:80], track), one=True)
    if dup:
        run("UPDATE audio SET code=COALESCE(NULLIF(?,''),code), "
            "kind=COALESCE(NULLIF(?,''),kind), track=COALESCE(NULLIF(?,''),track) "
            "WHERE id=?", (code or "", source or "", track or "", dup["id"]))
        return False
    run("INSERT INTO audio (book, code, track, file_id, uid, kind, name, created) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (book["id"], code or "", track, file_id, uid, source or "audio", name[:80],
         today().isoformat()))
    return True


def audio_resort(bid):
    """Заново раскладывает все треки учебника по именам файлов."""
    b = BOOKS.get(bid)
    moved = 0
    for r_ in q("SELECT * FROM audio WHERE book=?", (bid,)):
        code, track, source = audio_match(b, r_["name"] or "")
        if code != (r_["code"] or None) or track != (r_["track"] or ""):
            run("UPDATE audio SET code=?, track=?, kind=COALESCE(NULLIF(?,''),kind) "
                "WHERE id=?", (code or "", track, source or "", r_["id"]))
            moved += 1
    return moved


def audio_dedupe(bid):
    """Убирает дубли: одинаковый файл или одинаковое имя внутри урока."""
    seen, killed = set(), 0
    for r_ in q("SELECT * FROM audio WHERE book=? ORDER BY id", (bid,)):
        key = (r_["uid"] or r_["file_id"], r_["code"] or "", (r_["name"] or "").lower())
        alt = (r_["uid"] or r_["file_id"],)
        if key in seen or alt in seen:
            run("DELETE FROM audio WHERE id=?", (r_["id"],))
            killed += 1
        else:
            seen.add(key)
            seen.add(alt)
    return killed


def screen_audio_book(bid):
    b = BOOKS.get(bid)
    rows_ = q("SELECT * FROM audio WHERE book=? ORDER BY code, id", (bid,))
    known = [r for r in rows_ if r["code"]]
    unknown = [r for r in rows_ if not r["code"]]
    lines = ["🎧 <b>Аудио — {}</b>".format(esc(b["title"])), "",
             "Разложено по урокам: <b>{}</b>".format(len(known))]
    by = {}
    for r in known:
        by.setdefault(r["code"], []).append(r)
    for code in sorted(by, key=lambda c: [int(x) for x in c.split(".")])[:12]:
        srcs = {}
        for t in by[code]:
            srcs[t["kind"] if t["kind"] in ("PB", "WB", "TB") else "—"] = \
                srcs.get(t["kind"] if t["kind"] in ("PB", "WB", "TB") else "—", 0) + 1
        lines.append("• {} — {}".format(code, ", ".join(
            "{} {}".format(k, v) for k, v in sorted(srcs.items()))))
    if len(by) > 12:
        lines.append("… и ещё {} уроков".format(len(by) - 12))
    missing = [l["code"] for u in b["units"] for l in u["lessons"]
               if not any(r["code"] == l["code"] for r in known)]
    if missing:
        lines += ["", "Без аудио пока: {}{}".format(
            ", ".join(missing[:14]), " …" if len(missing) > 14 else "")]
    rows = [[("➕ Загрузить пачкой", "bka_bulk:%s" % bid)],
            [("🔄 Разложить заново", "bka_sort:%s" % bid),
             ("🧹 Убрать дубли", "bka_dedup:%s" % bid)]]
    if unknown:
        lines += ["", "❓ Не разобрано: <b>{}</b>".format(len(unknown))]
        rows.append([("❓ Разобрать вручную ({})".format(len(unknown)),
                      "bka_fix:%s" % bid)])
    rows.append([("⬅️ Назад", "bks_open:%s" % bid)])
    return "\n".join(lines), rows


def screen_audio_fix(bid):
    b = BOOKS.get(bid)
    r = q("SELECT * FROM audio WHERE book=? AND (code IS NULL OR code='') ORDER BY id LIMIT 1",
          (bid,), one=True)
    if not r:
        return screen_audio_book(bid)
    left = q("SELECT COUNT(*) c FROM audio WHERE book=? AND (code IS NULL OR code='')",
             (bid,), one=True)["c"]
    return ("❓ <b>{}</b>\n\nК какому уроку отнести? Осталось разобрать: {}.\n"
            "Пришлите код урока сообщением — например <code>3.2</code>, "
            "или <code>WB 3.2</code>, если это трек из рабочей тетради.".format(
                esc(r["name"] or "трек"), left),
            [[("▶️ Послушать", "bka_send:%d" % r["id"])],
             [("🗑 Удалить", "bka_del:%d" % r["id"])],
             [("⬅️ Назад", "bka_book:%s" % bid)]])


def screen_audio_item(tid):
    t = q("SELECT * FROM audio WHERE id=?", (tid,), one=True)
    if not t:
        return "Трек не найден.", [[("⬅️ Назад", "books")]]
    b = BOOKS.get(t["book"]) or {"title": t["book"], "units": []}
    lines = ["🎧 <b>{}</b>".format(esc(t["name"] or t["track"] or "трек")), "",
             "{} · урок {}{}".format(esc(b.get("title", "")), t["code"] or "—",
                                     " · " + t["kind"] if t["kind"] in ("PB", "WB", "TB") else "")]
    lines += ["", "<b>Задание</b>", esc(t["task"]) if t["task"] else "<i>не задано</i>"]
    lines += ["", "<b>Ключи</b> <i>(только для вас)</i>",
              esc(t["answers"]) if t["answers"] else "<i>нет</i>"]
    un = ln = 1
    for u in b.get("units", []):
        for l in u["lessons"]:
            if l["code"] == t["code"]:
                un, ln = u["n"], l["n"]
    return "\n".join(lines), [
        [("▶️ Послушать", "bka_send:%d" % tid)],
        [("🤖 Сгенерировать задание", "bka_gen:%d" % tid)],
        [("✏️ Задание", "bka_task:%d" % tid), ("🔑 Ключи", "bka_ans:%d" % tid)],
        [("📍 Перенести в другой урок", "bka_move:%d" % tid), ("🗑 Удалить", "bka_del:%d" % tid)],
        [("⬅️ Назад", "bka:%s:%d:%d" % (t["book"], un, ln))]]


def ai_audio_task(tid):
    """Задание к треку и ключи — по контексту урока."""
    t = q("SELECT * FROM audio WHERE id=?", (tid,), one=True)
    b = BOOKS.get(t["book"])
    if not b or not t["code"]:
        return None
    un = ln = None
    for u in b["units"]:
        for l in u["lessons"]:
            if l["code"] == t["code"]:
                un, ln = u["n"], l["n"]
    if un is None:
        return None
    out = ai_complete(
        "Ты преподаватель английского. К аудиозаписи урока нужно короткое задание на "
        "аудирование и ключи.\n\n{}\n\nФайл: {}\n\n"
        "Верни ровно две части:\nTASK: 2–3 строки — что сделать ученику, пока он слушает "
        "(задание на английском, простое и конкретное, без пересказа содержания записи).\n"
        "KEY: ожидаемые ответы или что должно прозвучать — для преподавателя.\n"
        "Без markdown-звёздочек.".format(lesson_brief(b, un, ln), t["name"] or t["track"]),
        max_tokens=400, kind="audio")
    if not out:
        return None
    task, key = out, ""
    m = re.search(r"KEY\s*:", out)
    if m:
        task, key = out[:m.start()], out[m.end():]
    task = re.sub(r"^\s*TASK\s*:", "", task).strip()
    run("UPDATE audio SET task=?, answers=? WHERE id=?", (task[:800], key.strip()[:800], tid))
    return True


def screen_books():
    lines = ["📕 <b>Учебники</b>", ""]
    rows = []
    if not BOOKS:
        lines += ["Пока ни одного.", "",
                  "Пришлите мне файл карты учебника (.json) — я его подключу. "
                  "Файлы можно и положить в папку <code>books/</code> рядом с кодом."]
    for bid, b in BOOKS.items():
        u, l, w = book_stats(b)
        lines.append("• <b>{}</b> — {} юнитов, {} уроков, {} слов, {} мин".format(
            esc(b["title"]), u, l, w, b.get("lesson_minutes", 60)))
        rows.append([(b["title"][:24], "bks_open:%s" % bid)])
    rows.append([("⬅️ К ученикам", "menu")])
    return "\n".join(lines), rows


def screen_book_admin(bid):
    b = BOOKS.get(bid)
    if not b:
        return screen_books()
    u, l, w = book_stats(b)
    who = q("SELECT name FROM students WHERE book=? AND archived=0", (bid,))
    tracks = q("SELECT COUNT(*) c FROM audio WHERE book=?", (bid,), one=True)["c"]
    lines = ["📕 <b>{}</b>".format(esc(b["title"])), "",
             "Уровень: {} · занятие {} мин".format(b.get("level", "—"),
                                                   b.get("lesson_minutes", 60)),
             "{} юнитов · {} уроков · {} слов в списках".format(u, l, w),
             "Аудио загружено: {}".format(tracks)]
    if who:
        lines.append("Занимаются: {}".format(esc(", ".join(r["name"] for r in who))))
    rows = [[("📚 Юниты и лексика", "bks_units:%s:0" % bid)],
            [("🎧 Загрузить аудио пачкой", "bka_bulk:%s" % bid)],
            [("🗑 Удалить учебник", "bks_del:%s" % bid)],
            [("⬅️ Назад", "books")]]
    return "\n".join(lines), rows


def screen_book_units(bid, un=0):
    b = BOOKS.get(bid)
    if not un:
        rows, line = [], []
        for u in b["units"]:
            line.append(("{}. {}".format(u["n"], u["title"][:14]), "bks_units:%s:%d" % (bid, u["n"])))
            if len(line) == 2:
                rows.append(line); line = []
        if line:
            rows.append(line)
        return ("📚 <b>{}</b> — выберите юнит".format(esc(b["title"])),
                rows + [[("⬅️ Назад", "bks_open:%s" % bid)]])
    u = unit_of(b, un)
    wl = u.get("wordlist") or []
    lines = ["📚 <b>Юнит {}: {}</b>".format(u["n"], esc(u["title"])), ""]
    if u.get("vocabulary_topic"):
        lines.append("Тема: {}".format(esc(u["vocabulary_topic"])))
    lines += ["", "<b>Лексика юнита ({})</b>".format(len(wl)),
              esc(", ".join(wl)) if wl else "<i>пусто — ИИ будет опираться только на тему</i>"]
    rows = [[("✏️ Заменить список слов", "bks_wl:%s:%d" % (bid, un))],
            [("➕ Дописать слова", "bks_wladd:%s:%d" % (bid, un))],
            [("📝 Уроки юнита", "bks_les:%s:%d:0" % (bid, un))],
            [("⬅️ К юнитам", "bks_units:%s:0" % bid)]]
    return "\n".join(lines), rows


def screen_book_lessons(bid, un, ln=0):
    b = BOOKS.get(bid)
    u = unit_of(b, un)
    if not ln:
        rows = [[("{} {}".format(l["code"], l["title"][:22]), "bks_les:%s:%d:%d" % (bid, un, l["n"]))]
                for l in u["lessons"]]
        return ("📝 <b>Юнит {}</b> — выберите урок".format(un),
                rows + [[("⬅️ Назад", "bks_units:%s:%d" % (bid, un))]])
    l = lesson_of(b, un, ln)
    lines = ["📝 <b>{} {}</b>".format(l["code"], esc(l["title"])), ""]
    for key, name in (("objective", "Цель"), ("grammar", "Грамматика"),
                      ("vocabulary", "Лексика"), ("functional", "Функц. язык"),
                      ("reading", "Чтение"), ("listening", "Аудирование"),
                      ("speaking", "Говорение"), ("writing", "Письмо"),
                      ("phonics", "Фонетика")):
        if l.get(key):
            lines.append("{}: {}".format(name, esc(l[key])))
    if l.get("wb_page"):
        lines.append("Тетрадь: стр. {}".format(l["wb_page"]))
    tr = q("SELECT * FROM audio WHERE book=? AND code=? ORDER BY id", (bid, l["code"]))
    lines.append("Аудио: {}".format(", ".join(esc(t["name"] or t["track"] or "трек")
                                              for t in tr) if tr else "нет"))
    rows = [[("✏️ Цель", "bks_f:%s:%d:%d:objective" % (bid, un, ln)),
             ("✏️ Грамматика", "bks_f:%s:%d:%d:grammar" % (bid, un, ln))],
            [("✏️ Название", "bks_f:%s:%d:%d:title" % (bid, un, ln)),
             ("✏️ Лексика урока", "bks_f:%s:%d:%d:vocabulary" % (bid, un, ln))],
            [("🎧 Аудио урока", "bka:%s:%d:%d" % (bid, un, ln))],
            [("⬅️ К урокам", "bks_les:%s:%d:0" % (bid, un))]]
    return "\n".join(lines), rows


def audio_label(t):
    """«PB 1.02» вместо имени файла."""
    src = t["kind"] if t["kind"] in ("PB", "WB", "TB") else ""
    num = t["track"] or t["code"] or ""
    return " ".join(x for x in (src, num) if x) or (t["name"] or "трек")[:20]


def audio_sorted(bid, code):
    rows_ = q("SELECT * FROM audio WHERE book=? AND code=? ORDER BY id", (bid, code))

    def key(t):
        try:
            a, b_ = (t["track"] or "0.0").split(".")
            return (0 if t["kind"] == "PB" else 1, int(a), int(b_))
        except ValueError:
            return (2, 0, 0)
    return sorted(rows_, key=key)


def screen_lesson_audio(bid, un, ln):
    b = BOOKS.get(bid)
    l = lesson_of(b, un, ln)
    tr = audio_sorted(bid, l["code"])
    lines = ["🎧 <b>Аудио к уроку {} {}</b>".format(l["code"], esc(l["title"])), ""]
    if tr:
        by = {}
        for t in tr:
            by.setdefault(t["kind"] if t["kind"] in ("PB", "WB", "TB") else "—", []).append(t)
        lines.append(" · ".join("{}: {}".format(k, len(v)) for k, v in by.items()))
        with_task = sum(1 for t in tr if t["task"])
        lines.append("С заданием: {} из {}".format(with_task, len(tr)))
    else:
        lines.append("Пока ничего не загружено.")
    rows = [[("{}{}".format("📝 " if t["task"] else "🎧 ", audio_label(t)),
              "bka_item:%d" % t["id"])] for t in tr]
    rows += [[("➕ Загрузить трек", "bka_add:%s:%d:%d" % (bid, un, ln))],
             [("⬅️ Назад", "bks_les:%s:%d:%d" % (bid, un, ln))]]
    return "\n".join(lines), rows


def draft_get(sid, bid, code):
    return q("SELECT * FROM hw_draft WHERE student_id=? AND book=? AND code=?",
             (sid, bid, code), one=True)


def draft_put(sid, bid, code, text=None, audio=None):
    d = draft_get(sid, bid, code)
    if d:
        run("UPDATE hw_draft SET text=COALESCE(?,text), audio=COALESCE(?,audio), updated=? "
            "WHERE id=?", (text, audio, today().isoformat(), d["id"]))
    else:
        run("INSERT INTO hw_draft (student_id, book, code, text, audio, updated) "
            "VALUES (?,?,?,?,?,?)", (sid, bid, code, text or "", audio or "",
                                     today().isoformat()))
    return draft_get(sid, bid, code)


def screen_hw_draft(sid):
    """Черновик домашки по уроку: правится, дополняется, уходит ученику с аудио."""
    b = book_of(sid)
    if not b:
        return ("📝 Чтобы собрать домашку по уроку, выберите ученику учебник.",
                [[("📕 Выбрать учебник", "book:%d" % sid)],
                 [("📝 Обычная домашка", "hw:%d" % sid)],
                 [("⬅️ Назад", "st:%d" % sid)]])
    s = sget(sid)
    un, ln = s["unit"] or 1, s["lesson"] or 1
    l = lesson_of(b, un, ln)
    d = draft_get(sid, b["id"], l["code"])
    body = (d["text"] if d else "") or ""
    ids = [int(x) for x in (d["audio"] if d else "").split(",") if x.strip().isdigit()]
    tracks = audio_sorted(b["id"], l["code"])
    lines = ["📝 <b>Домашка — {}</b>".format(esc(s["name"])),
             "{} · {} {}".format(esc(b["title"]), l["code"], esc(l["title"])), ""]
    lines.append(esc(body) if body else "<i>Пока пусто. Сгенерируйте или напишите сами.</i>")
    if ids:
        names = [audio_label(t) for t in tracks if t["id"] in ids]
        lines += ["", "🎧 Приложено: {}".format(esc(", ".join(names)) or len(ids))]
    rows = [[("🤖 Сгенерировать", "hwd_gen:%d" % sid),
             ("✏️ Переписать", "hwd_edit:%d" % sid)],
            [("➕ Дописать пункт", "hwd_add:%d" % sid),
             ("📚 Лексика урока", "hwd_voc:%d" % sid)]]
    if tracks:
        rows.append([("🎧 Аудио ({} шт.)".format(len(tracks)), "hwd_audio:%d" % sid)])
    rows += [[("📤 Отправить ученику", "hwd_send:%d" % sid)],
             [("⬅️ К уроку", "book:%d" % sid)]]
    return "\n".join(lines), rows


def screen_hw_audio(sid):
    b = book_of(sid)
    if not b:
        return screen_hw_draft(sid)
    s = sget(sid)
    l = lesson_of(b, s["unit"] or 1, s["lesson"] or 1)
    d = draft_get(sid, b["id"], l["code"])
    ids = [int(x) for x in (d["audio"] if d else "").split(",") if x.strip().isdigit()]
    tracks = audio_sorted(b["id"], l["code"])
    rows = [[("{} {}{}".format("☑️" if t["id"] in ids else "▫️", audio_label(t),
                               " 📝" if t["task"] else ""),
              "hwd_atog:%d:%d" % (sid, t["id"]))] for t in tracks]
    return ("🎧 Что приложить к домашке? Отмеченное уйдёт ученику вместе с заданием.",
            rows + [[("⬅️ Назад", "hwd:%d" % sid)]])


def unit_target_words(sid, n=12):
    b = book_of(sid)
    if not b:
        return []
    u = unit_of(b, sget(sid)["unit"] or 1)
    return (u.get("wordlist") or [])[:n] if u else []


def screen_book(sid):
    s = sget(sid)
    b = book_of(sid)
    if not b:
        rows = [[(bk["title"], "bk_set:%d:%s" % (sid, bid))] for bid, bk in BOOKS.items()]
        if not rows:
            return ("📕 Учебников не загружено. Положите файлы карт в папку "
                    "<code>books/</code> рядом с кодом.", [[("⬅️ Назад", "st:%d" % sid)]])
        return ("📕 <b>Учебник для {}</b>\n\nВыберите, по какому занимаетесь.".format(
            esc(s["name"])), rows + [[("⬅️ Назад", "st:%d" % sid)]])
    un, ln = s["unit"] or 1, s["lesson"] or 1
    u, l = unit_of(b, un), lesson_of(b, un, ln)
    lines = ["📕 <b>{}</b> · {} мин".format(esc(b["title"]), b.get("lesson_minutes", 60)), ""]
    if u and l:
        lines += ["Юнит {}: <b>{}</b>".format(u["n"], esc(u["title"])),
                  "Урок <b>{} {}</b>".format(l["code"], esc(l["title"])),
                  "Цель: {}".format(esc(l.get("objective", "—")))]
        for key, name in (("grammar", "Грамматика"), ("vocabulary", "Лексика"),
                          ("functional", "Функциональный язык"), ("writing", "Письмо"),
                          ("speaking", "Говорение"), ("phonics", "Фонетика")):
            if l.get(key):
                lines.append("{}: {}".format(name, esc(l[key])))
        if l.get("wb_page"):
            lines.append("Тетрадь: стр. {}".format(l["wb_page"]))
        have = q("SELECT COUNT(*) c FROM audio WHERE book=? AND code=?",
                 (b["id"], l["code"]), one=True)["c"]
        if have or l.get("tracks"):
            lines.append("Аудио: {}".format("{} шт. ✅".format(have) if have
                                            else "не загружено"))
    kids = (b.get("audience") or "").startswith(("дошк", "перв"))
    rows = [[("🗂 План занятия" if kids else "🗂 Lesson plan", "bk_go:%d:plan" % sid),
             ("🔥 Разминка", "bk_go:%d:warm" % sid)],
            [("🧩 Упражнения", "bk_go:%d:ex" % sid), ("📝 Домашка", "hwd:%d" % sid)],
            [("➕ Доп. лексика", "bk_go:%d:voc" % sid)],
            [("◀️ Урок", "bk_prev:%d" % sid), ("▶️ Урок", "bk_next:%d" % sid)],
            [("🎧 Аудио урока", "bka:%s:%d:%d" % (b["id"], un, ln)),
             ("✏️ Правка урока", "bks_les:%s:%d:%d" % (b["id"], un, ln))],
            [("📚 Выбрать урок", "bk_pick:%d:%d" % (sid, un)),
             ("📕 Сменить учебник", "bk_reset:%d" % sid)],
            [("⬅️ Назад", "st:%d" % sid)]]
    return "\n".join(lines), rows


def screen_book_pick(sid, un=0):
    b = book_of(sid)
    if not b:
        return screen_book(sid)
    if not un:
        rows = []
        line = []
        for u in b["units"]:
            line.append(("{}. {}".format(u["n"], u["title"][:16]), "bk_pick:%d:%d" % (sid, u["n"])))
            if len(line) == 2:
                rows.append(line); line = []
        if line:
            rows.append(line)
        return ("📚 <b>{}</b> — выберите юнит".format(esc(b["title"])),
                rows + [[("⬅️ Назад", "book:%d" % sid)]])
    u = unit_of(b, un)
    rows = [[("{} {}".format(l["code"], l["title"][:24]), "bk_lset:%d:%d:%d" % (sid, un, l["n"]))]
            for l in u["lessons"]]
    return ("📚 <b>Юнит {}: {}</b>\n\nВыберите урок.".format(u["n"], esc(u["title"])),
            rows + [[("⬅️ К юнитам", "bk_pick:%d:0" % sid)]])


def screen_warm(sid):
    c = lesson_context(sid)
    lines = ["🔥 <b>Warm-up — {}</b>".format(esc(c["name"])), "",
             "Соберу материал по лексике и грамматике, с которыми вы работали."]
    lines.append("Уровень: <b>{}</b> · слов в работе: <b>{}</b>".format(
        c["level"], len(c["words"])))
    if c["hard"]:
        lines.append("Западают: {}".format(esc(", ".join(h["term"] for h in c["hard"]))))
    if not AI_KEY:
        lines.append("\n<i>ИИ не подключён — соберу разминку по шаблону.</i>")
    rows = [[("⚡ Быстрая (5 минут)", "warmgo:%d:q" % sid)],
            [("📄 Полная (10–15 минут)", "warmgo:%d:f" % sid)],
            [("🎯 Задать грамматику или тему", "warmtopic:%d" % sid)],
            [("⬅️ Назад", "st:%d" % sid)]]
    return "\n".join(lines), rows


def send_warmup(chat_id, sid, full=False, topic=""):
    if AI_KEY:
        prompt, ai = ai_warmup(sid, topic=topic, full=full)
        if ai:
            head = "🔥 <b>Warm-up — {}</b>{}\n\n".format(
                esc(sget(sid)["name"]), " · " + esc(topic) if topic else "")
            return send_ai(chat_id, head + esc(ai), prompt, ai, "warmup", sid)
        send(chat_id, "⚠️ ИИ не ответил ({}), собрала по шаблону.\n"
                      "Проверить связь: /aitest".format(esc(AI_LAST["error"][:120] or "—")))
    return send(chat_id, text_warmup(sid))


def screen_after(sid, lid):
    """Что сделать сразу после отметки занятия."""
    s = sget(sid)
    les = q("SELECT * FROM lessons WHERE id=?", (lid,), one=True)
    hw = current_hw(sid)
    nxt = next_lesson_date(sid)
    lines = ["✅ <b>Занятие с {} записано</b>".format(esc(s["name"])), ""]
    lines.append("Тема: {}".format(esc(les["note"]) if les and les["note"] else "не записана"))
    lines.append("Домашка: {}".format(
        esc(hw["text"][:60]) if hw else "не задана"))
    if nxt:
        lines.append("Следующее занятие: {}".format(fmt_date(nxt)))
    if not s["tg_user_id"]:
        lines += ["", "<i>Ученик не подключён к боту — уведомления ему не уйдут.</i>"]
    rows = [[("✍️ Тема занятия", "note:%d:%d" % (sid, lid))],
            [("📝 Задать домашку", "afterhw:%d:%d" % (sid, lid))]]
    if book_of(sid):
        lines.append("Следующий урок: {}".format(esc(lesson_label(sid).split(" · ", 1)[-1])))
        rows.append([("📕 Материалы к следующему уроку", "book:%d" % sid)])
    rows += [
            [("📚 Добавить слова с урока", "afterw:%d:%d" % (sid, lid))],
            [("👤 К карточке", "st:%d" % sid), ("⬅️ К ученикам", "menu")]]
    return "\n".join(lines), rows


def screen_pay(sid):
    s = sget(sid)
    rate = s["rate"] or 0

    def label(n):
        return "{} зан.".format(n) + (" · {:,.0f}".format(n * rate).replace(",", " ") if rate else "")

    rows = [[(label(1), "payn:%d:1" % sid), (label(4), "payn:%d:4" % sid)],
            [(label(8), "payn:%d:8" % sid), ("✍️ Другое", "payc:%d" % sid)],
            [("⬅️ Назад", "st:%d" % sid)]]
    hint = "" if rate else "\nПодсказка: задайте ставку в «⚙️ Ещё» — сумма посчитается сама."
    return "💰 <b>Оплата — {}</b>\nСколько занятий оплачено?{}".format(esc(s["name"]), hint), rows


def screen_move(sid):
    occ = occurrences(sid, 6)
    if not occ:
        return ("🔁 Сначала задайте расписание — тогда можно будет переносить занятия.",
                [[("🗓 Расписание", "sched:%d" % sid)], [("⬅️ Назад", "st:%d" % sid)]])
    rows = [[("{} {} {}".format(WD_CAP[d.weekday()], fmt_date(d, True), t).strip(),
              "mv:%d:%s" % (sid, d.isoformat()))] for d, t, _ in occ]
    rows.append([("⬅️ Назад", "st:%d" % sid)])
    return "🔁 <b>Перенос</b>\nКакое занятие переносим?", rows


def screen_raw(sid):
    items = raw_words(sid)
    lines = ["🧺 <b>Сырые слова</b>", "",
             "Сюда складываются слова без перевода — они не попадают в повторение, "
             "пока вы их не оформите."]
    if items:
        lines.append(pre("\n".join(w["term"] for w in items[:40])))
        if len(items) > 40:
            lines.append("…и ещё {}".format(len(items) - 40))
    else:
        lines.append("\nПока пусто.")
    rows = [[("➕ Досыпать слов", "rawadd:%d" % sid)]]
    if items and AI_KEY and sget(sid)["is_self"]:
        rows.append([("✨ Оформить через ИИ ({})".format(min(len(items), 15)),
                      "rawai:%d" % sid)])
    if items:
        rows.append([("✍️ Оформить с переводом", "rawfix:%d" % sid)])
        rows.append([("🧹 Очистить", "rawclear:%d" % sid)])
    rows.append([("⬅️ Назад", "lrn:%d" % sid)])
    return "\n".join(lines), rows


def screen_hw(sid):
    s = sget(sid)
    hw = current_hw(sid)
    nxt = next_lesson_date(sid)
    lines = ["📝 <b>Домашка — {}</b>".format(esc(s["name"])), ""]
    if hw:
        lines.append("К занятию {}:".format(fmt_date(hw["due"]) if hw["due"] else "ближайшему"))
        lines.append(esc(hw["text"]))
    else:
        lines.append("Домашнего задания нет.")
    if nxt:
        lines.append("\nБлижайшее занятие: {}".format(fmt_date(nxt)))
    rows = [[("➕ Задать домашку", "hwadd:%d" % sid)]]
    if hw:
        rows.append([("✅ Снять задание", "hwdone:%d" % sid)])
    rows.append([("⬅️ Назад", "st:%d" % sid)])
    return "\n".join(lines), rows


def screen_mat(sid):
    s = sget(sid)
    items = materials_of(sid)
    lines = ["📎 <b>Материалы — {}</b>".format(esc(s["name"])), ""]
    open_rows = []
    if items:
        for m in items:
            tag = "🌐" if m["kind"] == "link" else ("🎁" if m["kind"] == "bonus" else "📄")
            scope = "" if m["student_id"] else " (общий)"
            ref = m["ref"] or ""
            if ref.startswith("http"):
                lines.append('{} <a href="{}">{}</a>{}'.format(
                    tag, esc(ref), esc(m["title"]), scope))
                lines.append("   <code>{}</code>".format(esc(ref[:80])))
                open_rows.append([("{} {}".format(tag, m["title"][:28]), ref)])
            else:
                lines.append("{} {}{}".format(tag, esc(m["title"]), scope))
    else:
        lines.append("Пока пусто.")
    rows = open_rows + [[("🌐 Добавить ссылку", "matlink:%d" % sid)],
            [("📄 Загрузить файл", "matfile:%d" % sid)],
            [("🎁 Добавить бонус (для ключиков)", "matbonus:%d" % sid)]]
    if items:
        rows.append([("🗑 Удалить", "matdel:%d" % sid)])
    rows.append([("⬅️ Назад", "st:%d" % sid)])
    return "\n".join(lines), rows


def screen_matdel(sid):
    items = materials_of(sid)
    rows = [[("🗑 {}".format(m["title"][:28]), "matrm:%d:%d" % (sid, m["id"]))] for m in items]
    rows.append([("⬅️ Назад", "mat:%d" % sid)])
    return "🗑 Что удалить?", rows


def screen_fb(sid):
    s = sget(sid)
    fb = q("SELECT * FROM feedback WHERE student_id=? ORDER BY id DESC LIMIT 8", (sid,))
    lines = ["💬 <b>Отзывы — {}</b>".format(esc(s["name"])), ""]
    if fb:
        for f in fb:
            who = "Вы" if f["side"] == "teacher" else ("Ученик" if not f["anon"] else "Аноним")
            star = " {}/5".format(f["rating"]) if f["rating"] else ""
            lines.append("<b>{}</b>{} · {}\n{}".format(
                who, star, fmt_date(f["created"], True), esc(f["text"] or "—")))
    else:
        lines.append("Пока нет.")
    avg = q("SELECT AVG(rating) a FROM feedback WHERE student_id=? AND rating IS NOT NULL",
            (sid,), one=True)["a"]
    if avg:
        lines.append("\nСредняя оценка занятий: <b>{}</b>/5".format(round(avg, 1)))
    rows = [[("✍️ Написать ученику", "fbwrite:%d" % sid)],
            [("📨 Запросить оценку", "fbask:%d" % sid)],
            [("⬅️ Назад", "st:%d" % sid)]]
    return "\n".join(lines), rows


def ai_spent(since=None):
    """Сколько токенов израсходовано: всего или с указанной даты."""
    sql = "SELECT COALESCE(SUM(in_tok),0) i, COALESCE(SUM(out_tok),0) o FROM ai_usage"
    args = ()
    if since:
        sql += " WHERE on_date>=?"
        args = (since,)
    r = q(sql, args, one=True)
    return (r["i"] or 0) + (r["o"] or 0)


def ai_budget_left():
    return AI_BUDGET - ai_spent() if AI_BUDGET else None


def ai_allowed():
    """(можно ли звать ИИ, причина отказа)."""
    if not AI_KEY:
        return False, "ИИ не подключён."
    if AI_BUDGET and ai_spent() >= AI_BUDGET:
        return False, "Запас токенов на ИИ исчерпан."
    if AI_DAILY_CAP and ai_spent(today().isoformat()) >= AI_DAILY_CAP:
        return False, "Дневной лимит ИИ исчерпан, попробуйте завтра."
    return True, ""


def ai_log(kind, sid, in_tok, out_tok):
    run("INSERT INTO ai_usage (on_date, ts, student_id, kind, in_tok, out_tok) "
        "VALUES (?,?,?,?,?,?)",
        (today().isoformat(), datetime.now().isoformat(timespec="seconds"),
         sid, kind, in_tok or 0, out_tok or 0))
    if AI_BUDGET and OWNER_ID:
        left = ai_budget_left()
        step = "aiwarn:%d" % (10 if left <= AI_BUDGET * 0.1 else (25 if left <= AI_BUDGET * 0.25
                                                                 else 0))
        if step != "aiwarn:0" and meta_get(step) != "1":
            meta_set(step, "1")
            send(OWNER_ID, "⚠️ Осталось {} токенов ИИ из {}.".format(
                fmt_num(left), fmt_num(AI_BUDGET)))


def fmt_num(n):
    return "{:,}".format(int(n)).replace(",", " ")


AI_LAST = {"when": "", "kind": "", "error": "", "ok": 0}


def ai_note(kind, error=""):
    AI_LAST.update({"when": datetime.now().strftime("%d.%m %H:%M"), "kind": kind,
                    "error": error[:400]})
    if not error:
        AI_LAST["ok"] = AI_LAST.get("ok", 0) + 1


def ai_remember(chat_id, prompt, output, kind, sid):
    """Запоминает последний запрос к ИИ, чтобы его можно было дополнить."""
    meta_set("lastai:%d" % chat_id, json.dumps(
        {"prompt": prompt[:6000], "output": output[:6000], "kind": kind, "sid": sid}))


def ai_last(chat_id):
    raw = meta_get("lastai:%d" % chat_id)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def send_ai(chat_id, text, prompt, output, kind, sid=None, extra_rows=None):
    """Отправляет результат ИИ и даёт кнопку, чтобы дописать к нему уточнение."""
    ai_remember(chat_id, prompt, output, kind, sid)
    rows = []
    if AI_LAST.get("truncated"):
        text += "\n\n<i>Ответ оборвался на середине — нажмите «Продолжить».</i>"
        rows.append([("▶️ Продолжить", "aicont")])
    rows.append([("✏️ Дополнить или переделать", "airefine")])
    return send(chat_id, text, rows + (extra_rows or []))


def ai_refine(chat_id, request, max_tokens=3000):
    """Повторный запрос с учётом того, что уже было выдано, и новой просьбы."""
    last = ai_last(chat_id)
    if not last:
        return None, "Нечего дополнять — сначала попросите что-нибудь сгенерировать."
    prompt = ("{}\n\n--- Ты уже прислал этот вариант ---\n{}\n\n"
              "--- Преподаватель просит доработать ---\n{}\n\n"
              "Выдай новый вариант целиком, с учётом просьбы. Сохрани прежний формат "
              "и структуру блоков, если не просят другого.").format(
                  last["prompt"], last["output"], request)
    out = ai_complete(prompt, max_tokens=max_tokens,
                      kind=last.get("kind", "misc") + "+", sid=last.get("sid"))
    if not out:
        return None, "ИИ не ответил: {}".format(AI_LAST["error"][:120] or "—")
    ai_remember(chat_id, last["prompt"], out, last.get("kind", "misc"), last.get("sid"))
    return out, ""


def ai_conf():
    """Формат, адрес и модель: подобранные автоматически или из переменных окружения."""
    return (meta_get("ai_format") or AI_FORMAT,
            meta_get("ai_url") or AI_URL,
            meta_get("ai_model") or AI_MODEL)


def ai_base():
    """Корень адреса сервиса без стандартных окончаний."""
    url = (meta_get("ai_url") or AI_URL).strip().rstrip("/")
    for tail in ("/v1/chat/completions", "/chat/completions", "/v1/messages",
                 "/messages", "/v1"):
        if url.endswith(tail):
            url = url[:-len(tail)]
            break
    return url.rstrip("/")


def ai_call(prompt, max_tokens, fmt, url, model, timeout=90):
    """Один запрос. Возвращает (текст, usage, ошибка)."""
    payload = {"model": model, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    if fmt == "anthropic":
        headers = {"x-api-key": AI_KEY, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        if "api.anthropic.com" not in url:
            headers["Authorization"] = "Bearer " + AI_KEY
    else:
        headers = {"Authorization": "Bearer " + AI_KEY,
                   "Content-Type": "application/json", "x-api-key": AI_KEY}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        try:
            body = (json.loads(body).get("error") or {}).get("message", body)
        except Exception:
            pass
        return None, {}, "HTTP {}: {}".format(e.code, body)
    except Exception as e:
        return None, {}, "{}: {}".format(type(e).__name__, e)
    u = data.get("usage") or {}
    stop = data.get("stop_reason") or ""
    try:
        stop = stop or (data["choices"][0].get("finish_reason") or "")
    except (KeyError, IndexError, TypeError):
        pass
    AI_LAST["truncated"] = stop in ("max_tokens", "length")
    try:
        if fmt == "anthropic":
            out = "".join(b.get("text", "") for b in data.get("content", [])).strip()
        else:
            out = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return None, u, "непонятный ответ сервиса: " + json.dumps(data)[:200]
    if not out:
        return None, u, "пустой ответ (stop_reason: {})".format(data.get("stop_reason", "?"))
    return out, u, ""


def ai_probe():
    """Перебирает сочетания формата и адреса, запоминает рабочее. Возвращает текст отчёта."""
    if not AI_KEY:
        return "AI_KEY не задан."
    base = ai_base()
    model = meta_get("ai_model") or AI_MODEL
    tries = [("openai", base + "/v1/chat/completions"),
             ("anthropic", base + "/v1/messages"),
             ("openai", base + "/chat/completions"),
             ("anthropic", base + "/messages")]
    seen, report = set(), []
    for fmt, url in tries:
        if url in seen:
            continue
        seen.add(url)
        out, u, err = ai_call("Ответь одним словом: готово", 20, fmt, url, model, timeout=40)
        if out:
            meta_set("ai_format", fmt)
            meta_set("ai_url", url)
            ai_log("test", None, u.get("input_tokens", u.get("prompt_tokens", 0)),
                   u.get("output_tokens", u.get("completion_tokens", 0)))
            ai_note("test")
            return ("✅ <b>Заработало.</b>\n\nАдрес: <code>{}</code>\nФормат: <code>{}</code>\n"
                    "Модель: <code>{}</code>\n\nНастройки сохранены в боте, и он уже ими "
                    "пользуется. Чтобы они пережили переустановку, впишите те же значения "
                    "в переменные <code>AI_URL</code> и <code>AI_FORMAT</code>.".format(
                        esc(url), fmt, esc(model)))
        report.append("• <code>{}</code> ({}) — {}".format(esc(url.replace(base, "…")),
                                                           fmt, esc(err[:90])))
    return ("⚠️ Ни один вариант не подошёл.\n\n{}\n\nЕсли везде «404», проверьте Base URL "
            "в кабинете сервиса. Если «model not found» — название модели в "
            "<code>AI_MODEL</code>.".format("\n".join(report)))


def ai_complete(prompt, max_tokens=900, kind="misc", sid=None):
    """Запрос к ИИ. Возвращает текст или None, если ключа нет или сервис недоступен."""
    ok, why = ai_allowed()
    if not ok:
        ai_note(kind, why)
        return None
    fmt, url, model = ai_conf()
    out, u, err = ai_call(prompt, max_tokens, fmt, url, model)
    if u:
        ai_log(kind, sid, u.get("input_tokens", u.get("prompt_tokens", 0)),
               u.get("output_tokens", u.get("completion_tokens", 0)))
    if out:
        ai_note(kind)
        return out
    ai_note(kind, err)
    print("AI error:", err)
    return None


def lesson_context(sid, days=30):
    """Чем занимались: слова, трудные слова, домашка, заметки с занятий."""
    s_ = sget(sid)
    since = (today() - timedelta(days=days)).isoformat()
    ws = last_batch(sid, 12) or q(
        "SELECT * FROM words WHERE student_id=? AND COALESCE(raw,0)=0 ORDER BY id DESC LIMIT 12",
        (sid,))
    hard = hard_words(sid, days=14, limit=6)
    hw = current_hw(sid)
    notes = [l["note"] for l in q(
        "SELECT note FROM lessons WHERE student_id=? AND held_on>=? AND note IS NOT NULL "
        "AND note<>'' ORDER BY held_on DESC LIMIT 5", (sid, since))]
    return {"name": s_["name"], "level": level_of(sid), "words": list(ws),
            "hard": list(hard), "hw": hw["text"] if hw else "", "notes": notes}


def ai_warmup(sid, topic="", full=False):
    """Разминка к занятию по лексике и грамматике, с которыми ученик работал."""
    c = lesson_context(sid)
    if not c["words"] and not topic:
        return "", None
    pairs = "; ".join("{} — {}".format(w["term"], w["translation"]) for w in c["words"])
    weak = ", ".join(h["term"] for h in c["hard"])
    ctx = ["Ученик: {}, уровень {}.".format(c["name"], c["level"]),
           "Активная лексика: {}".format(pairs or "—")]
    if weak:
        ctx.append("Слова, которые он забывает чаще всего: {}".format(weak))
    if c["hw"]:
        ctx.append("Текущее домашнее задание: {}".format(c["hw"][:300]))
    if c["notes"]:
        ctx.append("Заметки с последних занятий: {}".format(" | ".join(n[:120]
                                                                      for n in c["notes"])))
    if topic:
        ctx.append("Преподаватель просит сделать упор на: {}".format(topic))
    grammar = ("Грамматический фокус возьми из заметок, домашнего задания или просьбы "
               "преподавателя. Если там ничего нет — выбери конструкцию, уместную для "
               "этого уровня, и назови её прямо.")
    blocks = (
        "1) LEAD-IN — три вопроса для устного старта, на них нельзя ответить одним словом;\n"
        "2) LEXIS — восемь предложений gap-fill (пропуск ______), каждое с одним словом "
        "ученика; предложения живые, с контекстом, не словарные;\n"
        "3) COLLOCATIONS — пять заданий на сочетаемость: предлог, устойчивая пара или "
        "словообразование от этих же слов;\n"
        "4) GRAMMAR — шесть предложений на трансформацию по грамматическому фокусу "
        "(перепиши, раскрой скобки, соедини), со словами ученика внутри;\n"
        "5) SPEAKING — два задания на говорение: короткая ситуация-ролёвка и вопрос "
        "на рассуждение;\n"
        "6) KEY — ключи ко всем пунктам, кроме говорения."
    ) if full else (
        "1) LEAD-IN — два вопроса для устного старта;\n"
        "2) LEXIS — шесть предложений gap-fill (пропуск ______) со словами ученика;\n"
        "3) GRAMMAR — четыре предложения на трансформацию по грамматическому фокусу;\n"
        "4) SPEAKING — два вопроса на говорение;\n"
        "5) KEY — ключи."
    )
    prompt = (
        "Ты опытный преподаватель английского, готовишь разминку к индивидуальному "
        "занятию. Материал должен быть таким, чтобы его можно было вести прямо с экрана.\n\n"
        "{}\n\n{}\n\nСделай блоки:\n{}\n\n"
        "Требования: английский естественный и современный, сложность строго под уровень "
        "{}; предложения не должны повторять друг друга по структуре; никаких пояснений "
        "от себя, только материал. Заголовки блоков — заглавными латиницей, как выше. "
        "Без markdown-звёздочек и без таблиц."
    ).format("\n".join(ctx), grammar, blocks, c["level"])
    return prompt, ai_complete(prompt, max_tokens=3000 if full else 1400,
                               kind="warmup", sid=sid)


def ai_format_raw(sid, limit=15, items=None):
    """Оформляет слова в полные карточки: транскрипция, определение, синонимы, пример."""
    items = list(items) if items is not None else raw_words(sid)[:limit]
    if not items:
        return 0, "Слов без карточки нет."
    ok, why = ai_allowed()
    if not ok:
        return 0, why
    terms = "\n".join("{}. {}{}".format(
        i + 1, w["term"], " = " + w["translation"] if w["translation"] else "")
        for i, w in enumerate(items))
    s_ = sget(sid)
    simple = bool(s_["is_guest"]) or (s_["access"] or "full") == "kid"
    if simple:
        prompt = (
            "Ты помогаешь школьнику вести словарь английского.\n"
            "Список (слово, иногда с переводом через знак =):\n{}\n\n"
            "Слово может быть на английском или на русском. Исправь опечатку, приведи "
            "к начальной форме, подбери самый простой и частотный перевод.\n"
            "Для каждой строки верни объект: n (номер строки), term (английское слово), "
            "translation (перевод на русский, одно-два слова)."
        ).format(terms)
        data = ai_json(prompt, max_tokens=60 * len(items) + 300, kind="cards", sid=sid)
        if not isinstance(data, list):
            return 0, "ИИ не ответил или вернул непонятный формат. Подробности: /ai"
        done = 0
        for i, obj in enumerate(data):
            if not isinstance(obj, dict):
                continue
            try:
                k = int(obj.get("n", 0)) - 1
            except (TypeError, ValueError):
                k = i
            src = items[k] if 0 <= k < len(items) else None
            if src is None:
                continue
            run("UPDATE words SET term=?, translation=?, raw=0, due=? WHERE id=?",
                (str(obj.get("term") or src["term"])[:80],
                 str(obj.get("translation") or "")[:120], today().isoformat(), src["id"]))
            done += 1
        return done, "" if done else "ИИ вернул пустой список. Подробности: /ai"
    prompt = (
        "Ты составляешь словарные карточки для преподавателя английского. "
        "Уровень владения языком: {}, поэтому определения и примеры должны быть "
        "взрослыми и точными, без упрощений.\n"
        "Список (слово, иногда с переводом через знак =):\n{}\n\n"
        "Слово может быть дано по-английски или по-русски — карточка всегда делается "
        "для английского слова. Если оно дано по-русски, подбери самый частотный "
        "английский эквивалент. Если перевод дан, сохрани его смысл, но исправь, "
        "если он неточен или не совпадает по форме. Опечатки в английском исправляй "
        "(strick → strict), слово приводи к начальной форме.\n\n"
        "Для каждой строки верни объект с полями:\n"
        "n — номер строки;\n"
        "term — слово по-английски в начальной форме;\n"
        "ipa — транскрипция символами МФА, без квадратных скобок;\n"
        "definition — определение по-английски, как в толковом словаре, до 15 слов;\n"
        "syn — 2-3 синонима через запятую;\n"
        "ant — 1-2 антонима через запятую (пустая строка, если их нет);\n"
        "coll — одно типичное сочетание с этим словом;\n"
        "example — предложение с этим словом, естественное и не учебное;\n"
        "translation — перевод на русский, 1-3 слова.\n\n"
        "Верни массив объектов в том же порядке."
    ).format(level_of(sid), terms)
    data = ai_json(prompt, max_tokens=260 * len(items) + 400, kind="cards", sid=sid)
    if not isinstance(data, list):
        return 0, "ИИ не ответил или вернул непонятный формат. Подробности: /ai"
    by_term = {(w["term"] or "").strip().lower(): w for w in items}
    done = 0
    for i, obj in enumerate(data):
        if not isinstance(obj, dict):
            continue
        src = None
        try:
            k = int(obj.get("n", 0)) - 1
            if 0 <= k < len(items):
                src = items[k]
        except (TypeError, ValueError):
            pass
        if src is None:
            src = by_term.get(str(obj.get("source") or "").strip().lower())
        if src is None:
            src = items[i] if i < len(items) else None
        if src is None:
            continue
        run("UPDATE words SET term=?, ipa=?, definition=?, syn=?, ant=?, coll=?, example=?, "
            "translation=?, raw=0, due=? WHERE id=?",
            (str(obj.get("term") or src["term"])[:80], str(obj.get("ipa") or "")[:60],
             str(obj.get("definition") or "")[:300], str(obj.get("syn") or "")[:120],
             str(obj.get("ant") or "")[:120], str(obj.get("coll") or "")[:120],
             str(obj.get("example") or "")[:300],
             str(obj.get("translation") or "")[:120], today().isoformat(), src["id"]))
        done += 1
    return done, "" if done else "ИИ вернул пустой список. Подробности: /ai"


def ai_json(prompt, max_tokens=1200, kind="misc", sid=None):
    """Просит ИИ вернуть JSON и разбирает его. None, если не вышло."""
    raw = ai_complete(prompt + "\n\nОтветь ТОЛЬКО валидным JSON, без пояснений "
                               "и без ```.", max_tokens, kind, sid)
    if not raw:
        return None
    head = raw.strip()[:200]
    raw = raw.strip().strip("`").strip()
    if raw.lower().startswith("json"):
        raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except ValueError:
        pass
    for a, b in (("{", "}"), ("[", "]")):
        i, j = raw.find(a), raw.rfind(b)
        if i != -1 and j > i:
            try:
                return json.loads(raw[i:j + 1])
            except ValueError:
                continue
    ai_note(kind, "ответ не разобрался как JSON. Начало ответа: " + head)
    return None


def text_warmup(sid):
    """Разминка из последних слов ученика: пропуски и вопросы."""
    ws = last_batch(sid, 8) or q(
        "SELECT * FROM words WHERE student_id=? AND COALESCE(raw,0)=0 ORDER BY id DESC LIMIT 8",
        (sid,))
    if not ws:
        return "Warm-up не из чего собрать — сначала добавьте ученику слова."
    random.shuffle(ws := list(ws))
    lines = ["🔥 <b>Warm-up — {}</b>".format(esc(sget(sid)["name"])), "",
             "<b>1. Вспомни слово</b>"]
    for i, w in enumerate(ws[:6], 1):
        term = w["term"]
        hint = term[0] + "_" * max(len(term) - 1, 1)
        lines.append("{}. {} — {} ({} букв)".format(i, esc(w["translation"]), hint, len(term)))
    lines += ["", "<b>2. Вставь слово</b>"]
    for i, w in enumerate(ws[:4], 1):
        lines.append("{}. I think ______ is important because… "
                     "<i>({})</i>".format(i, esc(w["translation"])))
    lines += ["", "<b>3. Ответь, используя новые слова</b>"]
    qs = ["When was the last time you saw something like this?",
          "How would you explain these words to a friend?",
          "Which of these words is the most useful for you and why?",
          "Tell a short story using three of these words."]
    for i, qq in enumerate(random.sample(qs, 3), 1):
        lines.append("{}. {}".format(i, qq))
    lines += ["", "Слова: " + ", ".join(esc(w["term"]) for w in ws[:8])]
    return "\n".join(lines)


def screen_sched(sid):
    s = sget(sid)
    cur = slots_text(sid)
    ap = q("SELECT * FROM appts WHERE student_id=? AND on_date>=? ORDER BY on_date, at",
           (sid, today().isoformat()))
    lines = ["🗓 <b>Расписание — {}</b>".format(esc(s["name"])), "",
             "Постоянное: " + (cur if cur else "не задано")]
    if ap:
        lines.append("Разовые даты: " + ", ".join(
            "{} {}".format(fmt_date(a["on_date"], True), a["at"] or "").strip() for a in ap))
    else:
        lines.append("Разовых дат нет")
    lines.append("\nЕсли постоянного расписания нет — просто добавляйте даты "
                 "на ближайшую неделю, ученик увидит их у себя.")
    rows = [[("🔁 Задать постоянное", "schedc:%d" % sid)],
            [("📌 Добавить разовые даты", "appt:%d" % sid)]]
    if ap:
        rows.append([("🧹 Убрать разовые даты", "apptdel:%d" % sid)])
    rows.append([("⬅️ Назад", "st:%d" % sid)])
    return "\n".join(lines), rows


def screen_wpick(sid, learner=False):
    ws = q("SELECT * FROM words WHERE student_id=? ORDER BY id DESC LIMIT 20", (sid,))
    back = "lw_back:%d" % sid if learner else "words:%d" % sid
    if not ws:
        return "Слов пока нет.", [[("⬅️ Назад", back)]]
    pref = "lwdl" if learner else "wdl"
    rows = [[("🗑 {} — {}".format(w["term"][:20], w["translation"][:20]),
              "%s:%d:%d" % (pref, sid, w["id"]))] for w in ws]
    rows.append([("⬅️ Назад", back)])
    return ("🗑 <b>Удаление слов</b>\nНажмите на слово, чтобы удалить. "
            "Показаны последние 20.", rows)


def screen_history(sid):
    s = sget(sid)
    ls = q("SELECT * FROM lessons WHERE student_id=? ORDER BY held_on DESC, id DESC LIMIT 15", (sid,))
    ps = q("SELECT * FROM payments WHERE student_id=? ORDER BY id DESC LIMIT 10", (sid,))
    mv = q("SELECT * FROM moves WHERE student_id=? AND to_date>=? ORDER BY to_date",
           (sid, today().isoformat()))
    lines = ["📋 <b>{}</b>".format(esc(s["name"])), "", "<b>Занятия</b>"]
    if ls:
        for l in ls:
            icon = "✅" if l["kind"] == "held" else ("🚫" if l["charged"] else "⭕️")
            extra = l["note"] or l["reason"] or ""
            lines.append("{} {}{}".format(icon, fmt_date(l["held_on"]),
                                          " — " + esc(extra) if extra else ""))
    else:
        lines.append("пока нет")
    lines += ["", "<b>Оплаты</b>"]
    if ps:
        for p in ps:
            line = "💰 {} — {} за {} зан.".format(
                fmt_date(p["paid_on"]), fmt_money(p["amount"]), p["lessons"])
            if p["receipt"]:
                line += " · <a href=\"{}\">чек</a>".format(esc(p["receipt"]))
            lines.append(line)
    else:
        lines.append("пока нет")
    if mv:
        lines += ["", "<b>Переносы</b>"]
        for m in mv:
            lines.append("🔁 {} → {} {}".format(fmt_date(m["from_date"], True),
                                                fmt_date(m["to_date"], True), m["at"] or ""))
    return "\n".join(lines), [[("⬅️ Назад", "st:%d" % sid)]]


def screen_month(chat_id):
    first = today().replace(day=1).isoformat()
    body = ["{:<11}{:>4}{:>9}{:>5}".format("Ученик", "зан", "оплата", "ост")]
    money = lessons = 0
    for s in students(chat_id):
        held = q("SELECT COUNT(*) c FROM lessons WHERE student_id=? AND held_on>=? AND kind='held'",
                 (s["id"], first), one=True)["c"]
        paid = q("SELECT COALESCE(SUM(amount),0) a FROM payments WHERE student_id=? AND paid_on>=?",
                 (s["id"], first), one=True)["a"]
        st = stats(s["id"])
        money += paid
        lessons += held
        body.append("{:<11}{:>4}{:>9}{:>5}".format(
            s["name"][:11], held, "{:,.0f}".format(paid).replace(",", " "), st["left"]))
    text = "📊 <b>Итоги месяца ({})</b>\n".format(today().strftime("%m.%Y"))
    text += pre("\n".join(body)) if len(body) > 1 else "\nДанных пока нет."
    text += "\nЗанятий: <b>{}</b>\nОплат: <b>{}</b>".format(lessons, fmt_money(money))
    return text, [[("⬅️ К ученикам", "menu")]]


KIND_RU = {"warmup": "разминки", "cards": "оформление карточек", "misc": "прочее"}


def text_ai_usage():
    if not AI_KEY:
        return "🤖 ИИ не подключён: не задан AI_KEY."
    week = (today() - timedelta(days=6)).isoformat()
    month = (today() - timedelta(days=29)).isoformat()
    tot = ai_spent()
    lines = ["🤖 <b>Расход ИИ</b>", "",
             "Сегодня: <b>{}</b>".format(fmt_num(ai_spent(today().isoformat()))),
             "За неделю: <b>{}</b>".format(fmt_num(ai_spent(week))),
             "За месяц: <b>{}</b>".format(fmt_num(ai_spent(month))),
             "Всего: <b>{}</b>{}".format(
                 fmt_num(tot),
                 " из {} (осталось {})".format(fmt_num(AI_BUDGET),
                                               fmt_num(max(AI_BUDGET - tot, 0)))
                 if AI_BUDGET else "")]
    if AI_DAILY_CAP:
        lines.append("Дневной потолок: {}".format(fmt_num(AI_DAILY_CAP)))
    kinds = q("SELECT kind, SUM(in_tok+out_tok) t, COUNT(*) c FROM ai_usage "
              "GROUP BY kind ORDER BY t DESC LIMIT 8")
    if kinds:
        lines += ["", "<b>По типам</b>"]
        for k in kinds:
            name = KIND_RU.get(k["kind"], k["kind"])
            if k["kind"].startswith("ex:"):
                name = "упражнение: " + k["kind"][3:]
            elif k["kind"].startswith("check:"):
                name = "проверка: " + k["kind"][6:]
            lines.append("• {} — {} ({})".format(name, fmt_num(k["t"]), k["c"]))
    who = q("SELECT s.name name, SUM(a.in_tok+a.out_tok) t FROM ai_usage a "
            "JOIN students s ON s.id=a.student_id GROUP BY a.student_id "
            "ORDER BY t DESC LIMIT 5")
    if who:
        lines += ["", "<b>По ученикам</b>"]
        for r in who:
            lines.append("• {} — {}".format(esc(r["name"]), fmt_num(r["t"])))
    fmt, url, model = ai_conf()
    lines += ["", "<i>Модель: {} · формат: {}</i>".format(esc(model), fmt),
              "<i>Адрес: {}</i>".format(esc(url))]
    if AI_LAST["when"]:
        if AI_LAST["error"]:
            lines += ["", "⚠️ <b>Последняя ошибка</b> ({}, {}):\n<code>{}</code>".format(
                AI_LAST["when"], esc(AI_LAST["kind"]), esc(AI_LAST["error"]))]
        else:
            lines.append("<i>Последний запрос: {} — успешно</i>".format(AI_LAST["when"]))
    return "\n".join(lines)


def ai_selftest():
    """Проверка связи: если текущие настройки не работают — подбирает рабочие."""
    if not AI_KEY:
        return "🤖 AI_KEY не задан — переменная пустая или не сохранилась в панели."
    fmt, url, model = ai_conf()
    out, u, err = ai_call("Ответь одним словом: готово", 20, fmt, url, model, timeout=40)
    if out:
        ai_note("test")
        if u:
            ai_log("test", None, u.get("input_tokens", u.get("prompt_tokens", 0)),
                   u.get("output_tokens", u.get("completion_tokens", 0)))
        return ("✅ ИИ отвечает.\nМодель: <code>{}</code>\nОтвет: {}\n\n"
                "Формат: {} · адрес: <code>{}</code>".format(
                    esc(model), esc(out[:60]), fmt, esc(url)))
    ai_note("test", err)
    low = err.lower()
    if "authentication" in low or "401" in low or "invalid" in low and "key" in low:
        return ("⚠️ Ключ не принят сервисом.\nОшибка: <code>{}</code>\n\n"
                "Проверьте <code>AI_KEY</code> — он мог скопироваться не целиком или с "
                "пробелом. И убедитесь, что ключ не заморожен в кабинете.".format(esc(err)))
    if "credit" in low or "billing" in low or "402" in low or "баланс" in low:
        return "⚠️ Сервис говорит, что закончились средства или токены:\n<code>{}</code>".format(
            esc(err))
    if "429" in low:
        return "⚠️ Слишком часто — сервис ограничил запросы. Подождите минуту и повторите."
    # 404, неверный путь, непонятный ответ — пробуем подобрать адрес сами
    return ("⚠️ По текущему адресу сервис не отвечает (<code>{}</code>).\n"
            "Подбираю рабочее сочетание…\n\n{}".format(esc(err[:90]), ai_probe()))


def text_day(chat_id):
    """Сегодняшние занятия. Имя ученика — скрытая ссылка на его Zoom."""
    items = []
    for s in students(chat_id):
        st = stats(s["id"])
        for d, t, k in occurrences(s["id"], 3):
            if d != today():
                break
            items.append((t or "--:--", s, st, k))
    if not items:
        return ""
    items.sort(key=lambda x: x[0])
    lines = ["☀️ <b>Сегодня занятия</b> — {}".format(fmt_date(today(), True)), ""]
    has_zoom = False
    for t, s, st, k in items:
        z = zoom_link(s)
        if z:
            has_zoom = True
            who = '<a href="{}">{}</a>'.format(esc(z), esc(s["name"]))
        else:
            who = "<b>{}</b>".format(esc(s["name"]))
        marks = [x for x in (KIND_WORD.get(k, "").strip(),
                             "оплата!" if st["left"] <= 0 else "") if x]
        lines.append("🕐 <b>{}</b> — {}{}".format(
            t, who, " · " + " · ".join(marks) if marks else ""))
    if has_zoom:
        lines += ["", "<i>Имя ученика — ссылка на его занятие.</i>"]
    return "\n".join(lines)


def screen_week(chat_id):
    plan = {}
    for s in students(chat_id):
        st = stats(s["id"])
        for d, t, k in occurrences(s["id"], 14):
            if (d - today()).days > 6:
                break
            plan.setdefault(d, []).append((t, s["name"], st["left"], k))
    if not plan:
        return ("🗓 <b>Ближайшая неделя</b>\n\nРасписание не задано ни у кого.",
                [[("⬅️ К ученикам", "menu")]])
    out = []
    for d in sorted(plan):
        out.append("{} {}".format(WD_CAP[d.weekday()], fmt_date(d, True)))
        for t, name, left, k in sorted(plan[d]):
            flag = " !" if left <= 0 else ""
            out.append(" {:<6}{:<11}{:>2}{}{}".format(t or "--:--", name[:11], left,
                                                      KIND_SHORT.get(k, ""), flag))
    text = ("🗓 <b>Ближайшая неделя</b>\n" + pre("\n".join(out)) +
            "\nЦифра — остаток оплаченных, «!» — оплата кончилась, «п» — перенос.")
    return text, [[("📅 Постоянное расписание", "sched_all")], [("⬅️ К ученикам", "menu")]]


def screen_schedule_all(chat_id):
    grid = {}
    for s in students(chat_id):
        for x in q("SELECT weekday, at FROM slots WHERE student_id=?", (s["id"],)):
            grid.setdefault(x["weekday"], []).append((x["at"] or "", s["name"]))
    if not grid:
        return ("📅 <b>Моё расписание</b>\n\nПостоянное расписание ещё не задано.",
                [[("⬅️ К ученикам", "menu")]])
    out, total = [], 0
    for wd in range(7):
        if wd not in grid:
            continue
        for i, (t, name) in enumerate(sorted(grid[wd])):
            out.append("{:<4}{:<7}{}".format(WD_CAP[wd] if i == 0 else "", t or "--:--", name[:13]))
            total += 1
    text = ("📅 <b>Моё расписание</b>\n" + pre("\n".join(out)) +
            "\nВсего {} {} в неделю.".format(total, plural(total)))
    return text, [[("🗓 Ближайшая неделя", "week")], [("⬅️ К ученикам", "menu")]]


def screen_archive(chat_id):
    rows = [[(s["name"], "unarch:%d" % s["id"])] for s in students(chat_id, archived=True)]
    rows.append([("⬅️ К ученикам", "menu")])
    text = "🗄 <b>Архив</b>\nНажмите, чтобы вернуть ученика в список."
    if len(rows) == 1:
        text = "🗄 Архив пуст."
    return text, rows


def screen_words(sid):
    s = sget(sid)
    total, due = word_count(sid), due_count(sid)
    ws = q("SELECT * FROM words WHERE student_id=? ORDER BY id DESC LIMIT 12", (sid,))
    lines = ["📚 <b>Словарь — {}</b>".format(esc(s["name"])), "",
             "Всего слов: {} · на повторение сегодня: {}".format(total, due)]
    if ws:
        lines.append(pre("\n".join("{:<16}{}".format(w["term"][:16], w["translation"][:16])
                                   for w in ws)))
        if total > 12:
            lines.append("Показаны последние 12.")
    else:
        lines.append("\nСлов пока нет.")
    rows = [[("➕ Добавить слова", "waddo:%d" % sid)],
            [("🗑 Удалить слова", "wpick:%d" % sid)],
            [("⬅️ Назад", "st:%d" % sid)]]
    if not s["tg_user_id"]:
        rows.insert(1, [("🔗 Подключить ученика", "code:%d" % sid)])
    return "\n".join(lines), rows


def text_progress(sid, own=False):
    s = sget(sid)
    p = progress(sid)
    who = "📈 <b>Мой прогресс</b>" if own else "📈 <b>Прогресс — {}</b>".format(esc(s["name"]))
    body = [
        "{:<22}{:>6}".format("Всего слов", p["total"]),
        "{:<22}{:>6}".format("Выучено (30+ дн.)", p["learned"]),
        "{:<22}{:>5}%".format("Доля выученных", p["pct"]),
        "{:<22}{:>6}".format("В работе", p["started"]),
        "{:<22}{:>6}".format("Ещё не начато", p["new"]),
        "{:<22}{:>6}".format("Повторов за 7 дней", p["rev7"]),
        "{:<22}{:>6}".format("Дней с занятиями /30", p["days30"]),
        "{:<22}{:>6}".format("Дней подряд", p["streak"]),
        "{:<22}{:>5}%".format("Ответов без ошибок", p["acc"]),
        "{:<22}{:>6}".format("Ждут повтора сегодня", p["due"]),
    ]
    tail = "\nПоследнее повторение: {}".format(fmt_date(p["last"]) if p["last"] else "ещё не было")
    return who + "\n" + pre("\n".join(body)) + tail


def screen_progress(sid):
    return text_progress(sid), [[("🏆 Рейтинг", "board")], [("⬅️ Назад", "st:%d" % sid)]]


def screen_board(chat_id, me_sid=None, real_names=True):
    text = ("🏆 <b>Рейтинг по словам</b>\n" + leaderboard(chat_id, me_sid, real_names) +
            "\nвыуч — слов выучено, % — доля выученных, 7дн — повторов за неделю.")
    back = "lrn:%d" % me_sid if (me_sid and not real_names) else "menu"
    return text, [[("⬅️ Назад", back)]]


def text_promo():
    return ("📚 <b>{}</b> — тренажёр английских слов\n\n"
            "Добавляете слова с переводом — бот сам напоминает, когда их пора повторить. "
            "Чем лучше вы помните слово, тем реже оно возвращается: интервалы растут "
            "от одного дня до месяца, как в Anki. Есть личный прогресс и общий рейтинг.\n\n"
            "Пользоваться можно без записи на занятия.\n\n"
            "👩‍🏫 <b>Автор бота — Алёна Петрова</b>\n"
            "{}\n\nЗапись на занятия: @{}".format(BOT_NAME, TEACHER_BIO, TEACHER_HANDLE))


def text_share_bot():
    uname = meta_get("username", "")
    link = "https://t.me/{}".format(uname) if uname else ""
    return text_promo() + ("\n\nБот: {}".format(link) if link else "")


def screen_welcome(sid=None):
    rows = [[("✍️ Записаться на занятия", "https://t.me/" + TEACHER_HANDLE)]]
    if sid:
        rows.append([("⬅️ Назад к словам", "lrn:%d" % sid)])
    else:
        rows.append([("📚 Учить слова", "guest_go")])
        rows.append([("🔑 У меня есть код", "have_code")])
    return text_promo(), rows


def screen_share(sid):
    rows = [[("📄 Выписка", "sh_st:%d" % sid)],
            [("💳 Напоминание об оплате", "sh_pay:%d" % sid)],
            [("🗓 Расписание", "sh_sch:%d" % sid)],
            [("🔗 Код: взрослый", "code:%d" % sid),
             ("🔗 Код: ребёнок", "codek:%d" % sid)],
            [("⬅️ Назад", "st:%d" % sid)]]
    return ("📤 <b>Сообщение для ученика</b>\nБот пришлёт его отдельным сообщением "
            "вниз чата — останется переслать ученику.", rows)


# --------------------------------------------------------- Тексты для пересылки

def text_statement(sid):
    s = sget(sid)
    st = stats(sid)
    ls = q("SELECT * FROM lessons WHERE student_id=? ORDER BY held_on DESC, id DESC LIMIT 5", (sid,))
    lines = ["📄 <b>{}</b> — занятия на {}".format(esc(s["name"]), fmt_date(today())), ""]
    lines.append("Проведено: {}".format(st["held"]))
    lines.append("Оплачено: {}".format(st["paid_lessons"]))
    lines.append("Остаток: <b>{}</b>".format(st["left"]) if st["left"] >= 0
                 else "К оплате: <b>{} {}</b>".format(-st["left"], plural(-st["left"])))
    if ls:
        lines += ["", "Последние занятия:"]
        for l in ls:
            mark = "" if l["kind"] == "held" else " (отмена)"
            lines.append("• {}{}{}".format(fmt_date(l["held_on"], True), mark,
                                           " — " + esc(l["note"]) if l["note"] else ""))
    occ = upcoming(sid, 3)
    if occ:
        lines += ["", "Ближайшие занятия: " + ", ".join(
            "{} {}".format(fmt_date(d, True), t).strip() for d, t, _ in occ)]
    return "\n".join(lines)


def text_reminder(sid):
    s = sget(sid)
    st = stats(sid)
    rate, dur = s["rate"] or 0, s["duration"] or 60
    if st["left"] > 1:
        body = "Осталось {} оплаченных {}.".format(st["left"], plural(st["left"]))
    elif st["left"] == 1:
        body = "Осталось одно оплаченное занятие — напишите, пожалуйста, какой пакет берём дальше 🙂"
    elif st["left"] == 0:
        body = "Оплаченные занятия закончились. Подскажите, какой пакет берём дальше?"
    else:
        need = -st["left"]
        body = "Провели {} {} сверх оплаты.".format(need, plural(need))
        if rate:
            body += " К оплате: {}.".format(fmt_money(need * rate))
    options = ""
    if rate:
        options = "\n\nПакеты ({} мин): 1 — {}, 4 — {}, 8 — {}".format(
            dur, fmt_money(rate), fmt_money(rate * 4), fmt_money(rate * 8))
    return "💳 <b>{}</b>\n\n{}{}".format(esc(s["name"]), body, options)


def text_schedule(sid):
    s = sget(sid)
    occ = upcoming(sid, max(stats(sid)["left"], 4))
    if not occ:
        return "Расписание для {} пока не задано.".format(esc(s["name"]))
    body = "\n".join("{:<4}{:<8}{}".format(WD_CAP[d.weekday()], fmt_date(d, True),
                                           (t or "") + KIND_WORD.get(k, ""))
                     for d, t, k in occ[:10])
    return "🗓 <b>Расписание — {}</b>\n".format(esc(s["name"])) + pre(body)


def text_invite(sid, kind="full"):
    s = sget(sid)
    col = "code" if kind == "full" else "code_kid"
    code = s[col]
    if not code:
        code = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        run("UPDATE students SET {}=? WHERE id=?".format(col), (code, sid))
    uname = meta_get("username", "")
    link = "https://t.me/{}".format(uname) if uname else "бота"
    if kind == "full":
        what = ("В боте видно, сколько занятий проведено и сколько осталось, "
                "когда ближайшие занятия, а ещё там словарь: слова приходят "
                "на повторение в нужные дни.")
        head = "🔗 <b>Код для взрослого ученика</b> (занятия + словарь)"
    else:
        what = ("В боте будет словарь: слова приходят на повторение в нужные дни, "
                "нужно нажимать «не помню / с трудом / легко».")
        head = "🔗 <b>Код для ребёнка</b> (только словарь)"
    return ("{}\n\nПерешлите ученику:\n\n"
            "Открой {} , нажми Start и отправь код: <code>{}</code>\n\n{}".format(
                head, link, code, what))


def text_when(sid):
    s = sget(sid)
    occ = upcoming(sid, 8)
    if not occ:
        return ("🗓 Ближайшие занятия пока не назначены.\n"
                "Преподаватель добавит даты — они появятся здесь.")
    body = "\n".join("{:<4}{:<8}{}".format(WD_CAP[d.weekday()], fmt_date(d, True),
                                           (t or "") + KIND_WORD.get(k, ""))
                     for d, t, k in occ)
    return "🗓 <b>Ближайшие занятия — {}</b>\n".format(esc(s["name"])) + pre(body)


# ----------------------------------------------------------------- Экраны ученика

def save_feedback(sid, rating=0, text="", anon=1, side="student"):
    run("INSERT INTO feedback (student_id, side, rating, text, anon, created) "
        "VALUES (?,?,?,?,?,?)",
        (sid, side, rating or None, text[:1000], 1 if anon else 0, today().isoformat()))
    s = sget(sid)
    who = "Аноним" if anon else s["name"]
    star = " · оценка {}/5".format(rating) if rating else ""
    if s["chat_id"]:
        send(s["chat_id"], "💬 <b>Отзыв от ученика</b> ({}){}\n\n{}".format(
            esc(who), star, esc(text or "без комментария")))


def ask_feedback(sid):
    rows = [[("{}".format(n), "fbr:%d:%d" % (sid, n)) for n in (1, 2, 3, 4, 5)],
            [("Позже", "lrn:%d" % sid)]]
    ok = notify_student(sid, "🙏 Оцените, пожалуйста, занятия за последний месяц: 1–5.\n"
                             "Потом можно будет добавить комментарий — что было хорошо "
                             "и что улучшить. Отзыв анонимный.", rows)
    if ok:
        meta_set("fb_asked:%d" % sid, today().isoformat())
    return ok


def text_next_lesson(sid):
    s = sget(sid)
    occ = upcoming(sid, 1)
    lines = ["📅 <b>Ближайшее занятие</b>"]
    if occ:
        d, t, k = occ[0]
        lines.append("{} {} {}{}".format(WD_CAP[d.weekday()], fmt_date(d), t,
                                         KIND_WORD.get(k, "")).rstrip())
    else:
        lines.append("Дата пока не назначена.")
    z = zoom_link(s)
    if z:
        lines.append('🎥 <a href="{}">Подключиться к занятию</a>'.format(esc(z)))
    elif s["zoom"]:
        lines.append("🎥 Zoom: {}".format(esc(s["zoom"])))
    hw = current_hw(sid)
    if hw:
        lines += ["", "📝 <b>Homework</b>", esc(hw["text"])]
    ws = last_batch(sid)
    if ws:
        lines += ["", "📚 <b>Слова к занятию</b>",
                  pre("\n".join("{:<18}{}".format(w["term"][:18], w["translation"][:20])
                                 for w in ws))]
    st = stats(sid)
    if st["left"] <= 1:
        lines += ["", "💳 Остаток занятий: {}. Реквизиты для оплаты: {}".format(
            max(st["left"], 0), PAY_DETAILS)]
    return "\n".join(lines)


# ----------------------------------------------------------------- Учебники

BOOKS_DIR = os.environ.get("TG_BOOKS_DIR", os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "books"))
BOOKS = {}


def load_books():
    """Карты учебников: файлы из папки books плюс всё, что загружено в бота."""
    BOOKS.clear()
    if os.path.isdir(BOOKS_DIR):
        for fn in sorted(os.listdir(BOOKS_DIR)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(BOOKS_DIR, fn), encoding="utf-8") as f:
                    b = json.load(f)
                if b.get("id") and b.get("units"):
                    BOOKS[b["id"]] = b
            except Exception as e:
                print("Не прочитался учебник", fn, e)
    try:
        for r in q("SELECT * FROM books"):
            try:
                b = json.loads(r["data"])
                if b.get("id") and b.get("units"):
                    BOOKS[b["id"]] = b
            except ValueError:
                pass
    except sqlite3.Error:
        pass
    return BOOKS


def save_book(b):
    """Сохраняет учебник в базу — переживает обновление кода и попадает в бэкап."""
    run("INSERT INTO books (id, data, updated) VALUES (?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated=excluded.updated",
        (b["id"], json.dumps(b, ensure_ascii=False), today().isoformat()))
    BOOKS[b["id"]] = b


def book_stats(b):
    units = len(b["units"])
    lessons = sum(len(u["lessons"]) for u in b["units"])
    words = sum(len(u.get("wordlist") or []) for u in b["units"])
    return units, lessons, words


def book_of(sid):
    s = sget(sid)
    return BOOKS.get(s["book"] or "")


def unit_of(book, un):
    return next((u for u in book["units"] if u["n"] == un), None)


def lesson_of(book, un, ln):
    u = unit_of(book, un)
    if not u:
        return None
    return next((l for l in u["lessons"] if l["n"] == ln), None)


def lesson_label(sid):
    """«Evolve 4 · Unit 3 · 3.2 Is It Worth It?» — для карточки ученика."""
    b = book_of(sid)
    if not b:
        return ""
    s = sget(sid)
    l = lesson_of(b, s["unit"] or 1, s["lesson"] or 1)
    u = unit_of(b, s["unit"] or 1)
    if not l or not u:
        return b["title"]
    return "{} · {} · {} {}".format(b["title"], u["title"], l["code"], l["title"])


def lesson_brief(b, un, ln):
    """Всё, что известно про урок — идёт в промпт и в план."""
    u, l = unit_of(b, un), lesson_of(b, un, ln)
    if not u or not l:
        return ""
    bits = ["Учебник: {} (уровень {}), занятие {} минут.".format(
        b["title"], b.get("level", "—"), b.get("lesson_minutes", 60))]
    if b.get("components"):
        bits.append("На занятии используются: {}. Указывай страницы каждого из них.".format(
            b["components"]))
    bits += [
        "Юнит {}: {}. Урок {} — {}.".format(u["n"], u["title"], l["code"], l["title"]),
        "Цель урока: {}".format(l.get("objective", ""))]
    for key, name in (("grammar", "Грамматика"), ("vocabulary", "Лексика"),
                      ("functional", "Функциональный язык"), ("reading", "Чтение"),
                      ("listening", "Аудирование"), ("speaking", "Говорение"),
                      ("writing", "Письмо"), ("phonics", "Фонетика")):
        if l.get(key):
            bits.append("{}: {}".format(name, l[key]))
    if u.get("pron"):
        bits.append("Произношение юнита: {}".format("; ".join(u["pron"])))
    wl = u.get("wordlist") or []
    if wl:
        bits.append("ЛЕКСИКА ЮНИТА (использовать только эти слова и словосочетания): "
                    + ", ".join(wl[:90]))
    elif u.get("vocabulary_topic"):
        bits.append("Лексическая тема юнита: {}".format(u["vocabulary_topic"]))
    if l.get("wb_page"):
        bits.append("Рабочая тетрадь: страница {}{}".format(
            l["wb_page"], " (" + ", ".join(l.get("wb_sections", [])) + ")"
            if l.get("wb_sections") else ""))
    if u.get("video"):
        bits.append("Видео юнита: {}".format(u["video"]["title"]))
    if l.get("tracks"):
        bits.append("Аудиотреки урока: {}".format(", ".join(l["tracks"])))
    if l.get("tb_notes"):
        bits.append("Заметки из книги учителя (опирайся на них): {}".format(l["tb_notes"]))
    try:
        tr = q("SELECT name, task, answers FROM audio WHERE book=? AND code=? "
               "AND (task<>'' OR answers<>'')", (b["id"], l["code"]))
    except sqlite3.Error:
        tr = []
    if tr:
        bits.append("Загруженное аудио урока и задания к нему: " + " | ".join(
            "{}: {}{}".format(t["name"] or "трек", (t["task"] or "").replace("\n", " ")[:160],
                              " [ключи: {}]".format((t["answers"] or "").replace("\n", " ")[:120])
                              if t["answers"] else "") for t in tr[:6]))
    return "\n".join(bits)


def cache_get(book, code, kind):
    r = q("SELECT body FROM materials_cache WHERE book=? AND code=? AND kind=? "
          "ORDER BY id DESC LIMIT 1", (book, code, kind), one=True)
    return r["body"] if r else None


def cache_put(book, code, kind, body):
    run("INSERT INTO materials_cache (book, code, kind, body, created) VALUES (?,?,?,?,?)",
        (book, code, kind, body, today().isoformat()))


BOOK_KINDS = {
    "plan": ("🗂 Lesson plan", "Write a STEP-BY-STEP teacher's script for this lesson IN "
             "ENGLISH, detailed enough to teach from without opening the Teacher's Book.\n"
             "Start with PREPARE: what to have ready (pages, audio, board, printouts).\n"
             "Then numbered steps, each with: minutes, stage name, the exact words the "
             "teacher says in quotation marks, what goes on the board, which page and "
             "exercise number, what students do, interaction (T-S, pairs, groups), and how "
             "you know they got it — concept questions with expected answers, instruction "
             "check questions. Show the transition sentence between steps. Keep every "
             "instruction one short sentence.\n"
             "Timings must add up to the lesson length exactly.\n"
             "Finish with ANSWER KEY — answers to every task in the plan and the expected "
             "answers or target language for the coursebook exercises you refer to; mark "
             "with (?) anything you cannot be sure of and point to the Teacher's Book page "
             "instead of inventing. Then ANTICIPATED PROBLEMS with solutions."),
    "plan_kids": ("🗂 План занятия", "Составь пошаговый сценарий занятия для офлайн-урока "
                  "с маленькими детьми — так, чтобы вести прямо по нему, не открывая книгу "
                  "учителя.\n"
                  "Сначала блок PREPARE: что принести, распечатать, какие карточки и "
                  "игрушки приготовить, какие аудио включить.\n"
                  "Дальше пронумерованные шаги, у каждого: минуты, название этапа, "
                  "ТОЧНЫЕ фразы преподавателя на английском в кавычках, что показываете и "
                  "куда, что делают дети, страница книги и номер упражнения, номер аудио. "
                  "Между шагами — фраза-переход. Пояснения преподавателю по-русски, всё "
                  "обращённое к детям — по-английски.\n"
                  "Минуты должны в сумме дать длительность занятия.\n"
                  "В конце блок КЛЮЧИ — ответы ко всем заданиям плана и ожидаемые ответы "
                  "к упражнениям учебника; где не уверен — ставь (?) и отсылай к книге "
                  "учителя."),
    "warm": ("🔥 Разминка", "Составь разминку на 5–7 минут к этому уроку: два вопроса для "
             "устного старта, шесть предложений gap-fill (пропуск ______) на лексике юнита, "
             "четыре предложения на грамматику урока и ключи. Задания — на английском, "
             "пояснения для преподавателя — по-русски."),
    "ex": ("🧩 Упражнения", "Составь три упражнения по этому уроку: на лексику юнита, "
           "на грамматику урока и одно на говорение. К каждому — инструкция для ученика "
           "и ключи."),
    "hw": ("📝 Домашка", "Составь домашнее задание к этому уроку так, чтобы его можно было "
           "отправить ученику как есть: что сделать в рабочей тетради (страница и разделы) "
           "и одно короткое задание на закрепление лексики или грамматики урока. "
           "Инструкции короткие и понятные, сами задания на английском."),
    "voc": ("➕ Доп. лексика", "Подбери восемь дополнительных единиц по теме урока строго под "
            "уровень: коллокации, устойчивые выражения, а для уровня B1 и выше — идиомы и "
            "поговорки. Для каждой: единица — перевод на русский — пример предложения. "
            "Формат строк: единица | перевод | пример. Ничего лишнего."),
}


def ai_book_material(sid, kind, force=False):
    """Материал по текущему уроку учебника. Возвращает (текст, промпт, из кэша)."""
    b = book_of(sid)
    if not b:
        return None, "", False
    s = sget(sid)
    un, ln = s["unit"] or 1, s["lesson"] or 1
    l = lesson_of(b, un, ln)
    if not l:
        return None, "", False
    code = "{}:{}".format(b["id"], l["code"])
    if not force:
        got = cache_get(b["id"], l["code"], kind)
        if got:
            return got, "", True
    title, task = BOOK_KINDS[kind]
    extra = ""
    if kind in ("warm", "ex", "voc"):
        ws = [w["term"] for w in ex_words(sid, 8)]
        if ws:
            extra = "\nСлова ученика из его личного словаря: {}.".format(", ".join(ws))
    prompt = ("Ты опытный преподаватель английского, готовишь материал к занятию.\n\n"
              "{}\n\nУченик: уровень {}.{}\n\n{}\n\n"
              "Правила: лексику бери только из лексики юнита, новые слова вводи лишь если "
              "задание прямо про дополнительную лексику; английский естественный; "
              "без markdown-звёздочек; сразу материал, без вступлений."
              ).format(lesson_brief(b, un, ln), level_of(sid), extra, task)
    out = ai_complete(prompt, max_tokens=3500 if kind.startswith("plan") else 2200,
                      kind="book:" + kind, sid=sid)
    if out:
        cache_put(b["id"], l["code"], kind, out)
    return out, prompt, False


# --------------------------------------------------------------- Напоминания

WD_NAMES = {"понедельник": 0, "вторник": 1, "среда": 2, "среду": 2, "четверг": 3,
            "пятница": 4, "пятницу": 4, "суббота": 5, "субботу": 5,
            "воскресенье": 6, "пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4,
            "сб": 5, "вс": 6}


def parse_when(text, base=None):
    """«через 2 часа», «завтра в 10», «25.09 18:00», «в пятницу» → datetime или None."""
    t = text.lower().strip()
    now = base or datetime.now()
    m = re.search(r"через\s+(\d+)\s*(мин|час|дн|нед)", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return now + {"мин": timedelta(minutes=n), "час": timedelta(hours=n),
                      "дн": timedelta(days=n), "нед": timedelta(weeks=n)}[unit]

    day = None
    dm = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b", t)
    if dm:
        y = int(dm.group(3) or now.year)
        y = y + 2000 if y < 100 else y
        try:
            day = date(y, int(dm.group(2)), int(dm.group(1)))
            t = t.replace(dm.group(0), " ")
        except ValueError:
            day = None

    hour = minute = None
    hm = re.search(r"\b(\d{1,2})[:.](\d{2})\b", t)
    if hm and int(hm.group(1)) <= 23 and int(hm.group(2)) <= 59:
        hour, minute = int(hm.group(1)), int(hm.group(2))
    else:
        hm2 = re.search(r"\bв\s+(\d{1,2})\b", t)
        if hm2 and int(hm2.group(1)) <= 23:
            hour, minute = int(hm2.group(1)), 0

    if day is None:
        if "послезавтра" in t:
            day = now.date() + timedelta(days=2)
        elif "завтра" in t:
            day = now.date() + timedelta(days=1)
        elif "сегодня" in t or "вечером" in t or "утром" in t:
            day = now.date()
        else:
            for name, wd in WD_NAMES.items():
                if re.search(r"\b{}\b".format(name), t):
                    day = now.date() + timedelta(days=(wd - now.weekday()) % 7 or 7)
                    break

    if hour is None:
        if "утром" in t:
            hour, minute = 9, 0
        elif "вечером" in t:
            hour, minute = 19, 0
    if day is None and hour is None:
        return None
    if hour is None:
        hour, minute = 9, 0
    when = datetime.combine(day or now.date(), dtime(hour, minute))
    if when <= now:
        when += timedelta(days=1) if day is None else timedelta(days=365)
    return when


def note_repeat(text):
    t = text.lower()
    if "каждый день" in t or "ежедневно" in t:
        return "daily"
    if "каждую неделю" in t or "еженедельно" in t or "каждый понедельник" in t:
        return "weekly"
    if "каждый месяц" in t or "ежемесячно" in t:
        return "monthly"
    return None


def note_save(chat_id, text, when, file_id=None, file_kind=None, file_name=None):
    return run("INSERT INTO notes (chat_id, text, file_id, file_kind, file_name, due, "
               "repeat, done, created) VALUES (?,?,?,?,?,?,?,0,?)",
               (chat_id, text[:1500], file_id, file_kind, file_name,
                when.isoformat(timespec="minutes"), note_repeat(text),
                datetime.now().isoformat(timespec="seconds")))


def fmt_when(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%dT%H:%M")
    except ValueError:
        return iso
    day = "сегодня" if d.date() == today() else (
        "завтра" if d.date() == today() + timedelta(days=1) else fmt_date(d.date(), True))
    return "{} в {:02d}:{:02d}".format(day, d.hour, d.minute)


def screen_notes(chat_id):
    rows_ = q("SELECT * FROM notes WHERE chat_id=? AND done=0 ORDER BY due LIMIT 20",
              (chat_id,))
    lines = ["⏰ <b>Напоминания</b>", ""]
    if not rows_:
        lines += ["Пока пусто.", "",
                  "Можно писать прямо сюда: <code>напомни завтра в 10 позвонить в клинику</code>",
                  "Или прислать файл или ссылку с подписью «напомни в пятницу»."]
    btns = []
    for r_ in rows_:
        mark = "🔁 " if r_["repeat"] else ""
        clip = "📎 " if r_["file_id"] else ""
        lines.append("{}{}<b>{}</b> — {}".format(
            mark, clip, fmt_when(r_["due"]), esc((r_["text"] or r_["file_name"] or "")[:60])))
        btns.append([(("{} {}".format(fmt_when(r_["due"]),
                                      (r_["text"] or r_["file_name"] or "")[:20])),
                      "nt_item:%d" % r_["id"])])
    return "\n".join(lines), btns + [[("➕ Новое", "nt_add")], [("⬅️ К ученикам", "menu")]]


def notes_job():
    """Отправляет напоминания, у которых подошло время."""
    now = datetime.now().isoformat(timespec="minutes")
    for r_ in q("SELECT * FROM notes WHERE done=0 AND due<=? ORDER BY due LIMIT 20", (now,)):
        head = "⏰ <b>Напоминание</b>\n\n{}".format(esc(r_["text"] or ""))
        if r_["file_id"]:
            tg("sendDocument" if r_["file_kind"] == "doc" else "sendPhoto",
               chat_id=r_["chat_id"],
               **{("document" if r_["file_kind"] == "doc" else "photo"): r_["file_id"]},
               caption=(r_["text"] or "")[:1000])
            send(r_["chat_id"], head, [[("✅ Готово", "nt_done:%d" % r_["id"])]])
        else:
            send(r_["chat_id"], head, [[("✅ Готово", "nt_done:%d" % r_["id"]),
                                        ("🔁 Через час", "nt_snooze:%d" % r_["id"])]])
        if r_["repeat"]:
            d = datetime.strptime(r_["due"], "%Y-%m-%dT%H:%M")
            step = {"daily": timedelta(days=1), "weekly": timedelta(weeks=1),
                    "monthly": timedelta(days=30)}[r_["repeat"]]
            while d <= datetime.now():
                d += step
            run("UPDATE notes SET due=? WHERE id=?",
                (d.isoformat(timespec="minutes"), r_["id"]))
        else:
            run("UPDATE notes SET done=1 WHERE id=?", (r_["id"],))


# -------------------------------------------------------------------- Деньги

MONEY_RE = re.compile(r"^([+\-]?)\s*([\d][\d \u00a0]*(?:[.,]\d{1,2})?)\s*(?:р|руб|₽)?\s*"
                      r"[-—:]?\s*(.*)$|^(.+?)\s+([+\-]?)([\d][\d \u00a0]*"
                      r"(?:[.,]\d{1,2})?)\s*(?:р|руб|₽)?$", re.I)


def money_parse(line):
    """«пятёрочка 1200», «1200 пятёрочка», «+5000 занятие» → (kind, сумма, название)."""
    line = line.strip()
    if not line:
        return None
    m = MONEY_RE.match(line)
    if not m:
        return None
    if m.group(2):
        sign, num, title = m.group(1), m.group(2), (m.group(3) or "").strip()
    else:
        title, sign, num = (m.group(4) or "").strip(), m.group(5), m.group(6)
    try:
        amount = float(num.replace(" ", "").replace("\u00a0", "").replace(",", "."))
    except ValueError:
        return None
    if amount <= 0 or not title:
        return None
    return ("income" if sign == "+" else "expense", amount, title[:60])


def looks_like_money(text):
    lines = [l for l in text.strip().splitlines() if l.strip()]
    return bool(lines) and len(lines) <= 20 and all(money_parse(l) for l in lines)


def fin_category(titles):
    """Категории для названий: сначала из справочника, остальное — одним запросом к ИИ."""
    out, unknown = {}, []
    for t in titles:
        key = t.strip().lower()
        row = q("SELECT category FROM fin_cat WHERE merchant=?", (key,), one=True)
        if row and row["category"]:
            out[t] = row["category"]
        else:
            unknown.append(t)
    if unknown and ai_allowed()[0]:
        data = ai_json(
            "Определи категорию траты по названию места или покупки.\n"
            "Категории строго из списка: {}\n\nНазвания:\n{}\n\n"
            "Верни массив объектов: n (номер), category (ровно из списка).".format(
                ", ".join(FIN_CATS),
                "\n".join("{}. {}".format(i + 1, t) for i, t in enumerate(unknown))),
            max_tokens=40 * len(unknown) + 200, kind="money")
        if isinstance(data, list):
            for obj in data:
                if not isinstance(obj, dict):
                    continue
                try:
                    i = int(obj.get("n", 0)) - 1
                except (TypeError, ValueError):
                    continue
                cat = str(obj.get("category") or "").strip()
                if 0 <= i < len(unknown) and cat in FIN_CATS:
                    out[unknown[i]] = cat
                    run("INSERT OR REPLACE INTO fin_cat (merchant, category) VALUES (?,?)",
                        (unknown[i].strip().lower(), cat))
    for t in titles:
        out.setdefault(t, "Прочее")
    return out


def fin_income(amount, title, d=None, category="Занятия"):
    """Записывает поступление в бюджет (например, оплату ученика)."""
    if not amount:
        return
    run("INSERT INTO fin_tx (on_date, kind, amount, title, category, created) "
        "VALUES (?,?,?,?,?,?)",
        ((d or today()).isoformat(), "income", float(amount), title[:60], category,
         datetime.now().isoformat(timespec="seconds")))


def fin_add(lines, d=None, force=None):
    """Записывает траты и поступления. Возвращает добавленные строки."""
    items = [money_parse(l) for l in lines]
    items = [i for i in items if i]
    if force:
        items = [(force, a, t) for k, a, t in items]
    if not items:
        return []
    cats = fin_category([t for k, a, t in items if k == "expense"])
    added = []
    for kind, amount, title in items:
        cat = cats.get(title, "Прочее") if kind == "expense" else "Доход"
        run("INSERT INTO fin_tx (on_date, kind, amount, title, category, created) "
            "VALUES (?,?,?,?,?,?)",
            ((d or today()).isoformat(), kind, amount, title, cat,
             datetime.now().isoformat(timespec="seconds")))
        added.append((kind, amount, title, cat))
    return added


def money(n):
    return "{:,.0f} ₽".format(n).replace(",", " ")


def fin_month(since=None, until=None):
    since = since or today().replace(day=1)
    until = until or today()
    rows = q("SELECT kind, category, SUM(amount) s, COUNT(*) c FROM fin_tx "
             "WHERE on_date BETWEEN ? AND ? GROUP BY kind, category ORDER BY s DESC",
             (since.isoformat(), until.isoformat()))
    inc = sum(r["s"] for r in rows if r["kind"] == "income")
    exp = sum(r["s"] for r in rows if r["kind"] == "expense")
    cats = [(r["category"], r["s"], r["c"]) for r in rows if r["kind"] == "expense"]
    return inc, exp, cats


def fin_free_month():
    """Сколько в среднем остаётся за месяц — по данным последних 90 дней."""
    since = today() - timedelta(days=90)
    r = q("SELECT COALESCE(SUM(CASE WHEN kind='income' THEN amount ELSE 0 END),0) i, "
          "COALESCE(SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END),0) e, "
          "MIN(on_date) d FROM fin_tx WHERE on_date>=?", (since.isoformat(),), one=True)
    if not r["d"]:
        return 0, 0
    days = max((today() - datetime.strptime(r["d"], "%Y-%m-%d").date()).days + 1, 7)
    return (r["i"] - r["e"]) * 30.0 / days, days


def credit_forecast(extra=0.0):
    """Гасим по минимальному платежу плюс свободные деньги — лавиной по ставке."""
    cs = [dict(id=c["id"], name=c["name"], bal=c["balance"] or 0,
               rate=(c["rate"] or 0) / 100.0 / 12, mp=c["min_pay"] or 0,
               fee=c["fee"] or 0)
          for c in q("SELECT * FROM credits WHERE closed=0 ORDER BY rate DESC")]
    if not cs:
        return [], 0, 0
    months, paid, closed = 0, 0.0, []
    while any(c["bal"] > 0 for c in cs) and months < 600:
        months += 1
        pool = extra
        for c in cs:
            if c["bal"] <= 0:
                continue
            c["bal"] += c["bal"] * c["rate"] + c["fee"]
            pay = min(c["mp"], c["bal"])
            c["bal"] -= pay
            paid += pay
        target = next((c for c in cs if c["bal"] > 0), None)
        if target and pool:
            pay = min(pool, target["bal"])
            target["bal"] -= pay
            paid += pay
        for c in cs:
            if c["bal"] <= 0.5 and not any(x[0] == c["name"] for x in closed):
                closed.append((c["name"], months))
    return closed, months, paid


def screen_money():
    inc, exp, cats = fin_month()
    free, days = fin_free_month()
    lines = ["💰 <b>Деньги — {} {}</b>".format(MONTHS[today().month - 1], today().year), "",
             "Поступления: <b>{}</b>".format(money(inc)),
             "Траты: <b>{}</b>".format(money(exp)),
             "Остаток месяца: <b>{}</b>".format(money(inc - exp))]
    if cats:
        lines += ["", "<b>На что уходит</b>"]
        for name, s, c in cats[:7]:
            share = round(s * 100 / exp) if exp else 0
            lines.append("• {} — {} ({}%)".format(name, money(s), share))
    cs = q("SELECT * FROM credits WHERE closed=0 ORDER BY rate DESC")
    if cs:
        total = sum(c["balance"] or 0 for c in cs)
        lines += ["", "<b>Кредиты</b> — всего {}".format(money(total))]
        for c in cs:
            lines.append("• {} — {} · {}% · платёж {}".format(
                esc(c["name"]), money(c["balance"] or 0), c["rate"] or 0,
                money(c["min_pay"] or 0)))
        closed, months, paid = credit_forecast(max(free, 0))
        if months:
            lines += ["", "<b>Прогноз</b>"]
            if free > 0:
                lines.append("Свободно в месяц: <b>{}</b> (по данным за {} дн.{})".format(
                    money(free), days, ", оценка грубая" if days < 21 else ""))
            for name, m in closed:
                lines.append("• {} закроется через {} {}".format(
                    esc(name), m, plural(m, ("месяц", "месяца", "месяцев"))))
            lines.append("Проценты и комиссии сверху: <b>{}</b>".format(
                money(max(paid - sum(c["balance"] or 0 for c in cs), 0))))
    else:
        lines += ["", "<i>Кредиты не заведены — добавьте, и появится прогноз.</i>"]
    rows = [[("➕ Трата", "fin_new:e"), ("➕ Поступление", "fin_new:i")],
            [("🧾 Сегодня", "fin_day"), ("📊 За месяц", "fin_month")],
            [("💳 Кредиты", "cr_list"), ("📁 Выгрузка", "fin_csv")],
            [("⬅️ К ученикам", "menu")]]
    return "\n".join(lines), rows


def screen_fin_day(d=None):
    d = d or today()
    rows_ = q("SELECT * FROM fin_tx WHERE on_date=? ORDER BY id DESC", (d.isoformat(),))
    lines = ["🧾 <b>Записи за {}</b>".format(fmt_date(d, True)), ""]
    if not rows_:
        lines.append("Пока пусто. Пришлите строкой: <code>пятёрочка 1200</code>")
    btns = []
    for r_ in rows_:
        lines.append("{} {} — {} · <i>{}</i>".format(
            "➕" if r_["kind"] == "income" else "➖", money(r_["amount"]),
            esc(r_["title"]), r_["category"]))
        btns.append([("{} {}".format(money(r_["amount"]), r_["title"][:16]),
                      "fin_item:%d" % r_["id"])])
    return "\n".join(lines), btns + [[("⬅️ Назад", "money")]]


def screen_fin_item(tid):
    r_ = q("SELECT * FROM fin_tx WHERE id=?", (tid,), one=True)
    if not r_:
        return "Запись не найдена.", [[("⬅️ Назад", "fin_day")]]
    text = "{} <b>{}</b> — {}\nКатегория: <b>{}</b>\n\nМожно поменять категорию — " \
           "запомню её и для следующих трат в этом месте.".format(
               "➕" if r_["kind"] == "income" else "➖", esc(r_["title"]),
               money(r_["amount"]), r_["category"])
    cats, row = [], []
    for c in FIN_CATS:
        row.append((c, "fin_cat:%d:%s" % (tid, c)))
        if len(row) == 2:
            cats.append(row)
            row = []
    if row:
        cats.append(row)
    return text, cats + [[("🗑 Удалить запись", "fin_del:%d" % tid)],
                         [("⬅️ Назад", "fin_day")]]


def screen_credits():
    cs = q("SELECT * FROM credits ORDER BY closed, rate DESC")
    if not cs:
        return ("💳 Кредитов пока нет.", [[("➕ Добавить", "cr_add")],
                                         [("⬅️ Назад", "money")]])
    lines = ["💳 <b>Кредиты</b>", ""]
    rows = []
    for c in cs:
        mark = "✅ " if c["closed"] else ""
        lines.append("{}<b>{}</b> — {} · {}% · платёж {}{}".format(
            mark, esc(c["name"]), money(c["balance"] or 0), c["rate"] or 0,
            money(c["min_pay"] or 0),
            " · комиссия {}".format(money(c["fee"])) if c["fee"] else ""))
        if not c["closed"]:
            rows.append([("💸 Платёж — {}".format(c["name"][:12]), "cr_pay:%d" % c["id"]),
                         ("✏️", "cr_edit:%d" % c["id"]), ("🗑", "cr_del:%d" % c["id"])])
    rows += [[("➕ Добавить", "cr_add")], [("⬅️ Назад", "money")]]
    return "\n".join(lines), rows


def fin_ask():
    """Вечерний вопрос о тратах — один раз в день."""
    if not FIN_HOUR or not OWNER_ID:
        return
    if datetime.now().hour < FIN_HOUR or datetime.now().hour >= 23:
        return
    if meta_get("finask") == today().isoformat():
        return
    meta_set("finask", today().isoformat())
    n = q("SELECT COUNT(*) c FROM fin_tx WHERE on_date=?", (today().isoformat(),),
          one=True)["c"]
    if n:
        return
    send(OWNER_ID, "💸 <b>Что сегодня потратили?</b>\n\nПришлите строками, как удобно:\n"
                   "<code>пятёрочка 1200\nцппк 250\n+4000 занятие Аня</code>\n\n"
                   "Категории подберу сама.",
         [[("Сегодня без трат", "fin_none")], [("💰 Открыть деньги", "money")]])


# ---------------------------------------------------------------- Упражнения ИИ

EX_TYPES = [
    ("translate", "✍️ Перевод фраз", "5 фраз с русского на английский", ("text",),
     "Составь 5 коротких бытовых фраз по-русски для перевода на английский. В каждой "
     "естественно используется одно из слов ученика. q — фраза по-русски, a — эталонный "
     "перевод."),
    ("context", "🧩 Слово в контексте", "выбрать верное употребление", ("choice",),
     "Составь 5 заданий: слово ученика и три предложения, где оно употреблено верно "
     "только в одном; остальные — правдоподобные, но неверные по смыслу или "
     "сочетаемости. q — само слово, options — три предложения, correct — номер верного "
     "с нуля, why — одно предложение, почему верно именно оно."),
    ("error", "🔍 Найди ошибку", "исправить 5 предложений", ("choice", "text"),
     "Составь 5 предложений со словами ученика, в каждом одна типичная ошибка "
     "русскоязычного студента (артикль, предлог, время, порядок слов). q — предложение "
     "с ошибкой, options — три варианта исправления, correct — номер верного с нуля, "
     "why — в чём была ошибка. Для письменного формата: a — исправленный вариант "
     "и объяснение."),
    ("colloc", "🔗 Сочетаемость", "предлоги и устойчивые пары", ("choice", "text"),
     "Составь 5 заданий на сочетаемость слов ученика: в предложении пропущен предлог "
     "или часть устойчивого сочетания, пропуск обозначь ______. q — предложение "
     "с пропуском, options — три варианта вставки, correct — номер верного с нуля, "
     "why — короткое пояснение. Для письменного формата: a — что вставить."),
    ("dialog", "🎭 Мини-диалог", "ответить репликами в ситуации", ("text",),
     "Придумай бытовую ситуацию и 5 реплик собеседника, на которые ученик отвечает, "
     "используя свои слова. q — реплика собеседника и подсказка, какое слово применить, "
     "a — пример подходящего ответа."),
]

LETTERS = ("A", "B", "C", "D")


def ex_words(sid, n=12):
    ws = q("SELECT * FROM words WHERE student_id=? AND COALESCE(raw,0)=0 "
           "ORDER BY COALESCE(seen,''), id DESC LIMIT ?", (sid, n))
    return ws


def ai_exercise(sid, kind, mode="text"):
    """Генерирует упражнение. Возвращает (данные, причина отказа)."""
    spec = next((x for x in EX_TYPES if x[0] == kind), None)
    if not spec:
        return None, "Неизвестное упражнение."
    ws = ex_words(sid)
    if len(ws) < 4:
        return None, "Нужно хотя бы 4 слова в словаре."
    ok, why = ai_allowed()
    if not ok:
        return None, why
    s = sget(sid)
    pairs = "; ".join("{} — {}".format(w["term"], w["translation"]) for w in ws)
    fields = ("items (массив из 5 объектов с полями q, options из трёх вариантов, "
              "correct — номер верного варианта начиная с нуля, why — пояснение)"
              if mode == "choice" else
              "items (массив из 5 объектов с полями q и a)")
    prompt = (
        "Ты помогаешь ученику практиковать английский по его собственной лексике.\n"
        "Уровень ученика: {}.\nСлова ученика: {}\n\n{}\n\n"
        "Верни объект с полями: title (короткое название по-русски), "
        "intro (одна строка-инструкция по-русски), {}."
    ).format(level_of(sid), pairs, spec[4], fields)
    data = ai_json(prompt, max_tokens=1300, kind="ex:" + kind, sid=sid)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None, "ИИ не ответил. Ключик не потрачен, попробуйте ещё раз."
    items = []
    for i in data["items"][:6]:
        if not isinstance(i, dict) or not i.get("q"):
            continue
        if mode == "choice":
            opts = [str(o)[:200] for o in (i.get("options") or []) if str(o).strip()][:4]
            if len(opts) < 2:
                continue
            try:
                correct = int(i.get("correct", 0))
            except (TypeError, ValueError):
                correct = 0
            items.append({"q": str(i["q"])[:300], "options": opts,
                          "correct": max(0, min(correct, len(opts) - 1)),
                          "why": str(i.get("why", ""))[:300]})
        else:
            items.append({"q": str(i["q"])[:400], "a": str(i.get("a", ""))[:400]})
    if not items:
        return None, "ИИ вернул пустое задание. Ключик не потрачен."
    return {"title": str(data.get("title") or spec[1])[:80],
            "intro": str(data.get("intro") or "")[:200], "items": items,
            "mode": mode}, ""


def ai_check(sid, kind, items, answers):
    """Проверяет ответы ученика одним запросом. Возвращает текст разбора."""
    body = "\n\n".join("{}. Задание: {}\nЭталон: {}\nОтвет ученика: {}".format(
        i + 1, it["q"], it["a"], answers[i] if i < len(answers) else "— (нет ответа)")
        for i, it in enumerate(items))
    prompt = (
        "Ты доброжелательный преподаватель английского. Проверь ответы ученика.\n\n{}\n\n"
        "Для каждого пункта дай строку: номер, значок (✅ верно, ⚠️ почти, ❌ мимо), "
        "краткий комментарий по-русски и правильный вариант, если ответ неточный. "
        "Эталон — ориентир, а не единственно верный ответ: засчитывай любые корректные "
        "варианты. В конце одна ободряющая строка и счёт вида 4/5. "
        "Без markdown-звёздочек, коротко."
    ).format(body)
    return ai_complete(prompt, max_tokens=700, kind="check:" + kind, sid=sid)


def screen_ex(sid, mode="choice"):
    s = sget(sid)
    mine = bool(s["is_self"])
    keys = 1 if mine else (s["keys"] or 0)
    lines = ["🎁 <b>Упражнения</b>", "",
             "Бот составит задание по вашим словам и проверит ответы.",
             "🔘 — отвечать кнопками, ✍️ — писать самому."]
    lines += (["", "<i>Свои упражнения — без ключиков.</i>"] if mine else
              ["Одно упражнение — один 🔑 ключик.", "",
               "Ключиков у вас: <b>{}</b>".format(keys)])
    lines.append("<i>Значок у задания — формат, который для него единственно "
                 "возможный.</i>")
    if not keys:
        lines += ["", "<i>Ключики дают за: все повторения за день, новую стадию питомца, "
                      "серию без пропусков и победу в рейтинге. Ещё их выдаёт "
                      "преподаватель.</i>"]
    rows = []
    if keys:
        other = "text" if mode == "choice" else "choice"
        rows.append([("Формат: {} → сменить на {}".format(
            "🔘 кнопками" if mode == "choice" else "✍️ письменно",
            "✍️ письменно" if mode == "choice" else "🔘 кнопками"),
            "lrn_ex:%d:%s" % (sid, other))])
        for k, title, hint, modes, _ in EX_TYPES:
            use = mode if mode in modes else modes[0]
            mark = "" if use == mode else (" · 🔘" if use == "choice" else " · ✍️")
            rows.append([("{}{}".format(title, mark),
                          "lrn_exgo:%d:%s:%s" % (sid, k, use))])
    rows.append([("⬅️ Назад", "lrn:%d" % sid)])
    return "\n".join(lines), rows


def screen_ex_q(sid, st):
    """Вопрос с вариантами ответа."""
    items = st["items"]
    i = st["i"]
    it = items[i]
    body = ["🎁 <b>{}</b>  ·  {} из {}".format(esc(st["title"]), i + 1, len(items)), "",
            esc(it["q"]), ""]
    for n, opt in enumerate(it["options"]):
        body.append("<b>{}.</b> {}".format(LETTERS[n], esc(opt)))
    rows = [[(LETTERS[n], "lrn_exa:%d:%d" % (sid, n)) for n in range(len(it["options"]))],
            [("🚫 Прервать", "lrn:%d" % sid)]]
    return "\n".join(body), rows


def screen_ex_result(sid, st, chosen):
    """Разбор ответа и переход к следующему вопросу."""
    it = st["items"][st["i"]]
    ok = chosen == it["correct"]
    head = "✅ Верно!" if ok else "❌ Мимо. Верный вариант — <b>{}</b>.".format(
        LETTERS[it["correct"]])
    body = [head, "", "<b>{}</b>".format(esc(it["options"][it["correct"]]))]
    if it.get("why"):
        body += ["", "<i>{}</i>".format(esc(it["why"]))]
    last = st["i"] + 1 >= len(st["items"])
    score = st["score"] + (1 if ok else 0)
    if last:
        body += ["", "Итог: <b>{} из {}</b>".format(score, len(st["items"]))]
        rows = [[("🎁 Ещё упражнение", "lrn_ex:%d" % sid)], [("⬅️ В меню", "lrn:%d" % sid)]]
    else:
        body.append("")
        body.append("Счёт: {} из {}".format(score, st["i"] + 1))
        rows = [[("Дальше ▶️", "lrn_exn:%d" % sid)], [("🚫 Прервать", "lrn:%d" % sid)]]
    return "\n".join(body), rows


def ex_finish(sid, st):
    """Сохраняет итог теста с кнопками — он попадёт в недельную сводку."""
    run("INSERT INTO ex_log (on_date, student_id, kind, tasks, answers, feedback) "
        "VALUES (?,?,?,?,?,?)",
        (today().isoformat(), sid, st["kind"] + ":choice",
         "\n".join(it["q"] for it in st["items"])[:2000],
         "выбор вариантов",
         "Результат: {} из {}".format(st["score"], len(st["items"]))))


def ex_text(data):
    body = "\n\n".join("<b>{}.</b> {}".format(i + 1, esc(it["q"]))
                        for i, it in enumerate(data["items"]))
    return "🎁 <b>{}</b>\n{}\n\n{}\n\n<i>Пришлите ответы одним сообщением, " \
           "по одному в строке.</i>".format(
               esc(data["title"]), esc(data["intro"]), body)


# ------------------------------------------------------------------- Питомец

def pet(sid):
    """Состояние питомца. Ничего не хранится, кроме имени: всё считается из повторов."""
    s = sget(sid)
    total = q("SELECT COUNT(*) c FROM reviews WHERE student_id=?", (sid,), one=True)["c"]
    done = q("SELECT COUNT(*) c FROM reviews WHERE student_id=? AND on_date=?",
             (sid, today().isoformat()), one=True)["c"]
    stage = 0
    for i, (need, _, _) in enumerate(PET_STAGES):
        if total >= need:
            stage = i
    need_next, emoji, title = PET_STAGES[stage][0], PET_STAGES[stage][1], PET_STAGES[stage][2]
    to_next = PET_STAGES[stage + 1][0] - total if stage + 1 < len(PET_STAGES) else 0
    last = q("SELECT MAX(on_date) d FROM reviews WHERE student_id=?", (sid,), one=True)["d"]
    gap = None
    if last:
        gap = (today() - datetime.strptime(last, "%Y-%m-%d").date()).days
    fed = done >= PET_GOAL or (done > 0 and due_count(sid) == 0)
    if fed:
        mood, face = "сыт и доволен", "😊"
    elif done:
        mood, face = "уже разминается", "🙂"
    elif gap is None:
        mood, face = "ждёт знакомства", "👋"
    elif gap <= 1:
        mood, face = "проголодался", "😋"
    elif gap <= 3:
        mood, face = "скучает", "🥺"
    else:
        mood, face = "задремал", "😴"
    return {"name": s["pet_name"] or title, "emoji": emoji, "stage": stage, "title": title,
            "mood": mood, "face": face, "fed": fed, "done": done, "goal": PET_GOAL,
            "total": total, "to_next": to_next, "named": bool(s["pet_name"]),
            "need_next": need_next}


def pet_line(sid):
    """Короткая строка для главного экрана ученика."""
    p = pet(sid)
    return "{} <b>{}</b> — {} {} · сегодня {}/{}".format(
        p["emoji"], esc(p["name"]), p["mood"], p["face"], min(p["done"], p["goal"]), p["goal"])


def pet_bar(done, goal):
    full = min(done, goal)
    return "🟩" * full + "⬜" * max(goal - full, 0)


def screen_pet(sid):
    p = pet(sid)
    lines = ["{} <b>{}</b>".format(p["emoji"], esc(p["name"])), "",
             "Настроение: {} {}".format(p["mood"], p["face"]),
             "Сегодня: {} {}/{}".format(pet_bar(p["done"], p["goal"]),
                                        min(p["done"], p["goal"]), p["goal"])]
    if p["to_next"]:
        nxt = PET_STAGES[p["stage"] + 1]
        lines.append("До стадии «{} {}» — ещё {} {}".format(
            nxt[1], nxt[2], p["to_next"],
            plural(p["to_next"], ("повторение", "повторения", "повторений"))))
    else:
        lines.append("Это последняя стадия — питомец вырос!")
    pr = progress(sid)
    lines += ["", "Дней подряд: <b>{}</b> · всего повторений: <b>{}</b>".format(
        pr["streak"], p["total"])]
    if not p["fed"]:
        lines += ["", "<i>Чтобы покормить — повторите сегодня {} {}.</i>".format(
            p["goal"], plural(p["goal"], ("слово", "слова", "слов")))]
    due = due_count(sid)
    rows = [[("🔁 Повторить слова ({})".format(due), "lrn_go:%d" % sid)],
            [("✏️ {}".format("Переименовать питомца" if p["named"] else "Дать имя питомцу"),
              "lrn_petname:%d" % sid)],
            [("⬅️ Назад", "lrn:%d" % sid)]]
    return "\n".join(lines), rows


def pet_jobs():
    """Вечернее напоминание и поздравление с новой стадией."""
    now = datetime.now()
    for s in q("SELECT * FROM students WHERE tg_user_id IS NOT NULL AND archived=0"):
        sid = s["id"]
        if not word_count(sid):
            continue
        p = pet(sid)
        skey = "petstage:%d" % sid
        seen = meta_get(skey)
        if seen is None:
            meta_set(skey, str(p["stage"]))
        elif int(seen) < p["stage"]:
            meta_set(skey, str(p["stage"]))
            run("UPDATE students SET keys=COALESCE(keys,0)+1 WHERE id=?", (sid,))
            notify_student(sid, "🎉 <b>{}</b> подрос!\nТеперь это {} {}.\n"
                                "За это — 🔑 ключик на упражнение.".format(
                                    esc(p["name"]), p["emoji"], p["title"]),
                           [[("🎁 Потратить", "lrn_ex:%d" % sid)],
                            [("Посмотреть питомца", "lrn_pet:%d" % sid)]])
        if s["quiet"] or not PET_REMIND_HOUR or now.hour < PET_REMIND_HOUR \
                or now.hour >= 22:
            continue
        rkey = "petrem:%d" % sid
        if meta_get(rkey) == today().isoformat() or p["fed"]:
            continue
        meta_set(rkey, today().isoformat())
        notify_student(sid, "{} <b>{}</b> {}.\n{} {} — и он сыт до завтра.".format(
            p["emoji"], esc(p["name"]), p["mood"], PET_GOAL,
            plural(PET_GOAL, ("слово", "слова", "слов"))),
            [[("🔁 Повторить слова", "lrn_go:%d" % sid)],
             [("{} Посмотреть питомца".format(p["face"]), "lrn_pet:%d" % sid)]])


def screen_learner(sid):
    s = sget(sid)
    if s["is_guest"]:
        total, due = word_count(sid), due_count(sid)
        p = progress(sid)
        lines = ["📚 <b>{}</b> — тренажёр слов".format(BOT_NAME), "",
                 "Слов: <b>{}</b> · выучено: <b>{}</b> ({}%)".format(total, p["learned"], p["pct"]),
                 "На повторение сегодня: <b>{}</b>".format(due),
                 "Дней подряд: <b>{}</b>".format(p["streak"])]
        if total:
            lines += ["", pet_line(sid)]
        if not total:
            lines += ["", "Добавьте свои слова — по одному в строке:",
                      "<code>apple - яблоко</code>",
                      "Дальше бот сам будет напоминать, что пора повторить."]
        rows = [[("🔁 Повторить ({})".format(due), "lrn_go:%d" % sid)],
                [("➕ Добавить слова", "lrn_add:%d" % sid),
                 ("📖 Мои слова", "lw:%d" % sid)],
                [("🐣 Питомец", "lrn_pet:%d" % sid)],
                [("📈 Прогресс", "lrn_prog:%d" % sid), ("🏆 Рейтинг", "lrn_board:%d" % sid)],
                [("✍️ Записаться на занятия", "https://t.me/" + TEACHER_HANDLE)],
                [("👩‍🏫 О преподавателе", "promo"), ("🔑 У меня есть код", "have_code")]]
        return "\n".join(lines), rows
    if s["is_self"]:
        total, due = word_count(sid), due_count(sid)
        p = progress(sid)
        lines = ["📚 <b>Мой словарь</b>", "",
                 "Слов: <b>{}</b> · выучено: <b>{}</b> ({}%)".format(total, p["learned"], p["pct"]),
                 "На повторение сегодня: <b>{}</b>".format(due),
                 "Дней подряд: <b>{}</b>".format(p["streak"])]
        raw_n = len(raw_words(sid))
        rows = [[("🔁 Повторить ({})".format(due), "lrn_go:%d" % sid)],
                [("➕ Добавить слова", "lrn_add:%d" % sid),
                 ("📖 Мои слова", "lw:%d" % sid)]]
        if raw_n:
            rows.append([("🧺 Без карточки ({})".format(raw_n), "rawlist:%d" % sid)])
        rows += [[("🎁 Упражнения", "lrn_ex:%d" % sid)],
                [("📈 Прогресс", "lrn_prog:%d" % sid), ("🏆 Рейтинг", "board")],
                [("⬅️ К ученикам", "menu")]]
        return "\n".join(lines), rows
    if (s["access"] or "full") == "kid":
        total, due = word_count(sid), due_count(sid)
        lines = ["👋 <b>{}</b>".format(esc(s["name"])), "",
                 "📚 Слов в словаре: <b>{}</b>".format(total),
                 "На повторение сегодня: <b>{}</b>".format(due), "", pet_line(sid)]
        pt = pet(sid)
        rows = zoom_rows(s) + [
                [("🔁 Повторить слова ({})".format(due), "lrn_go:%d" % sid)],
                [("{} {}".format(pt["emoji"], pt["name"][:14]), "lrn_pet:%d" % sid),
                 ("🎁 Задания ({}🔑)".format(s["keys"] or 0), "lrn_ex:%d" % sid)],
                [("➕ Добавить слова", "lrn_add:%d" % sid),
                 ("📖 Мои слова", "lw:%d" % sid)],
                [("📈 Мой прогресс", "lrn_prog:%d" % sid),
                 ("🏆 Рейтинг", "lrn_board:%d" % sid)]]
        return "\n".join(lines), rows
    st = stats(sid)
    ls = q("SELECT * FROM lessons WHERE student_id=? AND kind='held' "
           "ORDER BY held_on DESC LIMIT 3", (sid,))
    lines = ["👋 <b>{}</b>".format(esc(s["name"])), "",
             "Проведено занятий: <b>{}</b>".format(st["held"]),
             "Остаток оплаченных: <b>{}</b>".format(max(st["left"], 0))]
    if st["left"] <= 0:
        lines.append("Оплаченные занятия закончились.")
    if ls:
        lines += ["", "Последние занятия:"]
        for l in ls:
            lines.append("• {}{}".format(fmt_date(l["held_on"], True),
                                         " — " + esc(l["note"]) if l["note"] else ""))
    occ = occurrences(sid, 3)
    if occ:
        lines += ["", "Ближайшие: " + ", ".join(
            "{} {}".format(fmt_date(d, True), t).strip() for d, t, _ in occ)]
    total, due = word_count(sid), due_count(sid)
    lines += ["", "📚 Словарь: {} слов, на сегодня {}".format(total, due)]
    if total:
        lines.append(pet_line(sid))
    if s["keys"]:
        lines.append("🔑 Ключиков: {} — можно открыть бонусный материал".format(s["keys"]))
    p = pet(sid)
    rows = zoom_rows(s) + [
            [("📅 Занятие", "lrn_next:%d" % sid), ("📎 Материалы", "lrn_mat:%d" % sid)],
            [("🔁 Повторить слова ({})".format(due), "lrn_go:%d" % sid)],
            [("{} {}".format(p["emoji"], p["name"][:14]), "lrn_pet:%d" % sid),
             ("🎁 Упражнения ({}🔑)".format(s["keys"] or 0), "lrn_ex:%d" % sid)],
            [("📚 Словарь", "lrn_words:%d" % sid), ("⚙️ Ещё", "lrn_more:%d" % sid)]]
    return "\n".join(lines), rows


def deck_stats(sid):
    """Состояние колоды как в Anki: новые, на изучении, молодые, зрелые."""
    rows_ = q("SELECT ivl, reps, lapses, ease, due FROM words "
              "WHERE student_id=? AND COALESCE(raw,0)=0", (sid,))
    st = {"new": 0, "learning": 0, "young": 0, "mature": 0, "total": len(rows_),
          "suspended": 0, "lapses": 0, "ease": []}
    for w in rows_:
        ivl, reps = w["ivl"] or 0, w["reps"] or 0
        st["lapses"] += w["lapses"] or 0
        if w["ease"]:
            st["ease"].append(w["ease"])
        if reps == 0:
            st["new"] += 1
        elif ivl == 0:
            st["learning"] += 1
        elif ivl < 21:
            st["young"] += 1
        else:
            st["mature"] += 1
    st["ease_avg"] = round(sum(st["ease"]) / len(st["ease"]), 2) if st["ease"] else 0
    return st


def forecast(sid, days=14):
    """Сколько карточек придёт на повторение в ближайшие дни."""
    out = []
    for i in range(days):
        d = (today() + timedelta(days=i)).isoformat()
        n = q("SELECT COUNT(*) c FROM words WHERE student_id=? AND COALESCE(raw,0)=0 "
              "AND due{}?".format("<=" if i == 0 else "="), (sid, d), one=True)["c"]
        out.append(n)
    return out


def review_history(sid, days=14):
    rows_ = q("SELECT on_date, COUNT(*) c, SUM(CASE WHEN grade=0 THEN 1 ELSE 0 END) bad "
              "FROM reviews WHERE student_id=? AND on_date>=? GROUP BY on_date",
              (sid, (today() - timedelta(days=days - 1)).isoformat()))
    by = {r["on_date"]: (r["c"], r["bad"]) for r in rows_}
    return [by.get((today() - timedelta(days=days - 1 - i)).isoformat(), (0, 0))
            for i in range(days)]


def spark(vals, width=8):
    """Столбики из символов — маленький график прямо в сообщении."""
    if not vals or not max(vals):
        return "▁" * len(vals)
    blocks = "▁▂▃▄▅▆▇█"
    top = max(vals)
    return "".join(blocks[min(int(v / top * (len(blocks) - 1) + 0.5), len(blocks) - 1)]
                   for v in vals)


def screen_deck_stats(sid):
    s = sget(sid)
    st = deck_stats(sid)
    p = progress(sid)
    hist = review_history(sid)
    fc = forecast(sid)
    total_rev = q("SELECT COUNT(*) c FROM reviews WHERE student_id=?", (sid,), one=True)["c"]
    ok = q("SELECT COUNT(*) c FROM reviews WHERE student_id=? AND grade>0", (sid,),
           one=True)["c"]
    days_active = q("SELECT COUNT(DISTINCT on_date) c FROM reviews WHERE student_id=?",
                    (sid,), one=True)["c"]
    lines = ["📊 <b>Статистика словаря</b>", "",
             "<b>Колода</b>",
             "🆕 Новые: <b>{}</b>".format(st["new"]),
             "📖 На изучении: <b>{}</b>".format(st["learning"]),
             "🌱 Молодые (&lt;21 дн.): <b>{}</b>".format(st["young"]),
             "🌳 Зрелые (21+ дн.): <b>{}</b>".format(st["mature"]),
             "Всего карточек: <b>{}</b>".format(st["total"]), "",
             "<b>Повторения</b>",
             "За 14 дней: {} ".format(spark([h[0] for h in hist])),
             "Всего: <b>{}</b> · верных: <b>{}%</b>".format(
                 total_rev, round(ok * 100 / total_rev) if total_rev else 0),
             "Дней с занятиями: <b>{}</b> · серия: <b>{}</b>".format(days_active, p["streak"]),
             "Забываний: <b>{}</b> · средняя лёгкость: <b>{}</b>".format(
                 st["lapses"], st["ease_avg"] or "—"), "",
             "<b>Прогноз на 14 дней</b>",
             "{} ".format(spark(fc)),
             "Сегодня: <b>{}</b> · завтра: <b>{}</b> · за неделю: <b>{}</b>".format(
                 fc[0], fc[1], sum(fc[:7]))]
    hard = hard_words(sid, days=30, limit=5)
    if hard:
        lines += ["", "<b>Труднее всего</b>"]
        for h in hard:
            lines.append("• {} — {} ({}×)".format(esc(h["term"]), esc(h["tr"] or ""), h["c"]))
    return "\n".join(lines), [[("🔁 Повторить ({})".format(due_count(sid)), "lrn_go:%d" % sid)],
                              [("⬅️ Назад", "lrn_words:%d" % sid)]]


def screen_words_menu(sid):
    due, total = due_count(sid), word_count(sid)
    p = progress(sid)
    return ("📚 <b>Словарь</b>\n\nСлов: <b>{}</b> · выучено: <b>{}</b> ({}%)\n"
            "На сегодня: <b>{}</b> · дней подряд: <b>{}</b>".format(
                total, p["learned"], p["pct"], due, p["streak"]),
            [[("🔁 Повторить ({})".format(due), "lrn_go:%d" % sid)],
             [("➕ Добавить слова", "lrn_add:%d" % sid), ("📖 Мои слова", "lw:%d" % sid)],
             [("📈 Прогресс", "lrn_prog:%d" % sid), ("📊 Статистика", "lrn_stats:%d" % sid)],
             [("🏆 Рейтинг", "lrn_board:%d" % sid)],
             [("⬅️ Назад", "lrn:%d" % sid)]])


def screen_more_menu(sid):
    s = sget(sid)
    rows = [[("💳 Оплата", "lrn_pay:%d" % sid), ("🗓 Все даты", "lrn_when:%d" % sid)],
            [("💬 Отзыв преподавателю", "lrn_fb:%d" % sid)],
            [("🔔 Напоминания: {}".format("выкл" if s["quiet"] else "вкл"),
              "lrn_quiet:%d" % sid)]]
    if s["keys"]:
        rows.append([("🔑 Открыть бонус ({})".format(s["keys"]), "lrn_key:%d" % sid)])
    rows += [[("💌 Поделиться ботом", "lrn_promo:%d" % sid)],
             [("🔄 Обновить", "lrn:%d" % sid), ("⬅️ Назад", "lrn:%d" % sid)]]
    return "⚙️ <b>Ещё</b>", rows


def card_back(w, pro=False):
    """Оборот карточки: термин, транскрипция, синонимы, сочетаемость, пример, перевод."""
    lines = ["<b>{}</b>{}".format(esc(w["term"]),
                                  " [{}]".format(esc(w["ipa"])) if w["ipa"] else "")]
    if not pro and w["definition"]:
        lines.append("<blockquote>{}</blockquote>".format(esc(w["definition"])))
    for tag, val in (("Syn", w["syn"]), ("Ant", w["ant"]), ("Coll", w["coll"])):
        if val:
            lines.append("<i>{}:</i> {}".format(tag, esc(val)))
    if w["example"]:
        ex = re.sub(r"(?i)\b({})\b".format(re.escape(w["term"])),
                    lambda m: "<b>{}</b>".format(m.group(0)), esc(w["example"]))
        lines += ["", "<i>Ex:</i> {}".format(ex)]
    if w["translation"]:
        lines += ["", "🇷🇺 <tg-spoiler>{}</tg-spoiler>".format(esc(w["translation"]))
                  if pro else "🇷🇺 {}".format(esc(w["translation"]))]
    return "\n".join(lines)


def screen_card(sid, word, show=False):
    if not word:
        p = pet(sid)
        tail = "\n\n{} <b>{}</b> {}.".format(
            p["emoji"], esc(p["name"]),
            "сыт и доволен" if p["fed"] else "ждёт ещё немного практики")
        return ("🎉 На сегодня всё — слов на повторение больше нет.\n"
                "Всего в словаре: {} слов.".format(word_count(sid)) + tail,
                [[("{} Питомец".format(p["face"]), "lrn_pet:%d" % sid)],
                 [("⬅️ В меню", "lrn:%d" % sid)]])
    s = sget(sid)
    pro = (bool(s["is_self"]) or (s["access"] or "full") == "full") and \
        bool(word["definition"]) and not s["is_guest"]
    head = "📚 Осталось: {}".format(due_count(sid))
    front = ("<blockquote>{}</blockquote>".format(esc(word["definition"])) if pro
             else "<b>{}</b>".format(esc(word["term"])))
    if not show:
        return "{}\n\n{}".format(head, front), [
            [("👀 Показать", "w_show:%d:%d" % (sid, word["id"]))],
            [("⬅️ Выйти", "lrn:%d" % sid)]]
    labels = (("❌", "Снова", 0), ("😕", "Трудно", 1), ("🙂", "Хорошо", 2), ("😎", "Легко", 3))
    ivls = " · ".join("{} {}".format(e, ivl_label(preview_ivl(word, g)))
                      for e, _, g in labels)
    text = "{}\n\n{}\n➖➖➖\n{}\n\n<i>{}</i>".format(
        head, front, card_back(word, pro), ivls)
    rows = [[("{} {}".format(e, n), "w_g:%d:%d:%d" % (sid, word["id"], g))
             for e, n, g in labels],
            [("🗑 Удалить слово", "w_del:%d:%d" % (sid, word["id"])),
             ("⬅️ Выйти", "lrn:%d" % sid)]]
    return text, rows


def screen_card_del(sid, word):
    """Подтверждение удаления прямо во время повторения."""
    return ("🗑 Удалить слово из словаря?\n\n<b>{}</b> — {}\n\n"
            "<i>Это навсегда: карточка и её история повторений исчезнут.</i>".format(
                esc(word["term"]), esc(word["translation"] or word["definition"] or "")),
            [[("🗑 Да, удалить", "w_delok:%d:%d" % (sid, word["id"]))],
             [("↩️ Нет, вернуться", "w_show:%d:%d" % (sid, word["id"]))]])


# ------------------------------------------------------------------------ Экспорт

def export_csv(chat_id):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Ученик", "Тип", "Дата", "Занятий", "Сумма", "Комментарий"])
    for s in list(students(chat_id)) + list(students(chat_id, archived=True)):
        for l in q("SELECT * FROM lessons WHERE student_id=? ORDER BY held_on", (s["id"],)):
            kind = "занятие" if l["kind"] == "held" else (
                "отмена (списано)" if l["charged"] else "отмена (без списания)")
            w.writerow([s["name"], kind, fmt_date(l["held_on"]), l["charged"], "", l["note"] or ""])
        for p in q("SELECT * FROM payments WHERE student_id=? ORDER BY paid_on", (s["id"],)):
            w.writerow([s["name"], "оплата", fmt_date(p["paid_on"]), p["lessons"],
                        "{:.0f}".format(p["amount"] or 0), p["note"] or ""])
        for x in q("SELECT * FROM words WHERE student_id=? ORDER BY id", (s["id"],)):
            w.writerow([s["name"], "слово", fmt_date(x["created"] or today().isoformat()), "", "",
                        "{} — {}".format(x["term"], x["translation"])])
    send_document(chat_id, "tutor_{}.csv".format(today().isoformat()), buf.getvalue(),
                  caption="Выгрузка на " + fmt_date(today()))
    send(chat_id, "✅ Файл с занятиями, оплатами и словами отправлен выше.")


# ----------------------------------------------- Запись занятия и напоминание мне

def record_lesson(chat_id, sid, d, kind="held", charged=1, reason=None):
    lid = run("INSERT INTO lessons (student_id, held_on, kind, charged, reason) "
              "VALUES (?,?,?,?,?)", (sid, d.isoformat(), kind, charged, reason))
    s = sget(sid)
    st = stats(sid)
    what = "Занятие" if kind == "held" else (
        "Отмена со списанием" if charged else "Отмена без списания")
    if reason:
        what += " ({})".format(reason)
    flash(chat_id, "✅ {} — <b>{}</b>, {}.\nОстаток: <b>{}</b> {}.".format(
        what, esc(s["name"]), fmt_date(d), st["left"], plural(st["left"])))
    if st["left"] == 1:
        send(chat_id, "🔔 У <b>{}</b> остался последний оплаченный урок — пора напомнить "
                      "об оплате. Готовое сообщение ниже 👇".format(esc(s["name"])))
        send(chat_id, text_reminder(sid))
    elif st["left"] <= 0:
        send(chat_id, "🔔 У <b>{}</b> оплаченные занятия закончились. "
                      "Готовое сообщение ниже 👇".format(esc(s["name"])))
        send(chat_id, text_reminder(sid))
    return lid


# ----------------------------------------------------------------------- Callback

def handle_callback(chat_id, message_id, cq_id, payload, user_id):
    parts = payload.split(":")
    cmd = parts[0]
    sid = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else None

    # экраны словаря доступны и ученику, и педагогу
    if cmd == "guest_go":
        toast(cq_id)
        g = make_guest(user_id)
        t, r = screen_learner(g["id"])
        return edit(chat_id, message_id, t, r)

    if cmd == "have_code":
        toast(cq_id)
        mine = student_by_user(user_id)
        back = "lrn:%d" % mine["id"] if (mine and not is_owner(user_id)) else "promo"
        return edit(chat_id, message_id,
                    "🔑 Отправьте код, который дал преподаватель, обычным сообщением.",
                    [[("⬅️ Назад", back)]])

    if cmd == "promo":
        toast(cq_id)
        mine = student_by_user(user_id)
        t, r = screen_welcome(mine["id"] if mine and not is_owner(user_id) else None)
        return edit(chat_id, message_id, t, r)

    if cmd in ("lrn", "lrn_go", "lrn_add", "lrn_when", "lw", "lw_back", "lwdl",
               "lrn_prog", "lrn_board", "lrn_promo", "lrn_nick", "lrn_renick",
               "lrn_next", "lrn_mat", "lrn_fb", "lrn_pay", "lrn_key", "lrn_file",
               "lrn_pet", "lrn_petname", "lrn_ex", "lrn_exgo", "lrn_exa", "lrn_exn",
               "lrn_words", "lrn_more", "w_del", "w_delok", "lrn_quiet", "lrn_stats",
               "fbr", "fbskip", "w_show", "w_g"):
        learner = student_by_user(user_id)
        if not is_owner(user_id):
            if not learner:
                learner = make_guest(user_id)
            sid = learner["id"]
        if not student(sid):
            toast(cq_id)
            t, r = screen_welcome()
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn":
            toast(cq_id)
            set_state(chat_id, pending=None)
            t, r = screen_learner(sid)
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_go":
            toast(cq_id)
            ws = due_words(sid, 1)
            t, r = screen_card(sid, ws[0] if ws else None)
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_add":
            toast(cq_id)
            set_state(chat_id, student_id=sid,
                      pending={"action": "words", "sid": sid, "by": "ученик"})
            return edit(chat_id, message_id,
                        "➕ Пришлите слова одним сообщением, по одному в строке:\n\n"
                        "<code>apple - яблоко\nto give up - сдаться</code>\n\n"
                        "Можно и просто слова без перевода — оформлю сама.",
                        [[("⬅️ Назад", "lrn:%d" % sid)]])
        if cmd == "lrn_quiet":
            run("UPDATE students SET quiet=1-COALESCE(quiet,0) WHERE id=?", (sid,))
            toast(cq_id, "Напоминания выключены" if sget(sid)["quiet"]
                  else "Напоминания включены")
            t, r = screen_more_menu(sid)
            return edit(chat_id, message_id, t, r)

        if cmd == "lrn_stats":
            toast(cq_id)
            t, r = screen_deck_stats(sid)
            return edit(chat_id, message_id, t, r)

        if cmd == "lrn_words":
            toast(cq_id)
            t, r = screen_words_menu(sid)
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_more":
            toast(cq_id)
            t, r = screen_more_menu(sid)
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_ex":
            toast(cq_id)
            t, r = screen_ex(sid, parts[2] if len(parts) > 2 else "choice")
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_exgo":
            kind = parts[2]
            mode = parts[3] if len(parts) > 3 else "text"
            s_ = sget(sid)
            if not s_["is_self"] and (s_["keys"] or 0) < 1:
                return toast(cq_id, "Нужен ключик")
            toast(cq_id, "Составляю задание…")
            edit(chat_id, message_id, "🎁 Составляю задание по вашим словам…", [])
            data, why = ai_exercise(sid, kind, mode)
            if not data:
                t, r = screen_ex(sid)
                return edit(chat_id, message_id, "⚠️ " + esc(why) + "\n\n" + t, r)
            if not s_["is_self"]:
                run("UPDATE students SET keys=MAX(COALESCE(keys,0)-1,0) WHERE id=?", (sid,))
            if mode == "choice":
                st = {"action": "exq", "sid": sid, "kind": kind, "title": data["title"],
                      "items": data["items"], "i": 0, "score": 0}
                set_state(chat_id, student_id=sid, pending=st)
                t, r = screen_ex_q(sid, st)
                return edit(chat_id, message_id, t, r)
            set_state(chat_id, student_id=sid,
                      pending={"action": "exdo", "sid": sid, "kind": kind,
                               "items": data["items"]})
            return edit(chat_id, message_id, ex_text(data),
                        [[("🚫 Отменить", "lrn:%d" % sid)]])

        if cmd in ("lrn_exa", "lrn_exn"):
            st = get_state(chat_id)["pending"] or {}
            if st.get("action") != "exq":
                toast(cq_id, "Задание уже закрыто")
                t, r = screen_ex(sid)
                return edit(chat_id, message_id, t, r)
            if cmd == "lrn_exa":
                chosen = int(parts[2])
                it = st["items"][st["i"]]
                ok = chosen == it["correct"]
                toast(cq_id, "Верно!" if ok else "Не то")
                t, r = screen_ex_result(sid, st, chosen)
                st["score"] += 1 if ok else 0
                st["answered"] = True
                if st["i"] + 1 >= len(st["items"]):
                    ex_finish(sid, st)
                    set_state(chat_id, pending=None)
                else:
                    set_state(chat_id, pending=st)
                return edit(chat_id, message_id, t, r)
            if not st.pop("answered", False):
                return toast(cq_id, "Сначала выберите вариант")
            st["i"] += 1
            toast(cq_id)
            set_state(chat_id, pending=st)
            t, r = screen_ex_q(sid, st)
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_pet":
            toast(cq_id)
            t, r = screen_pet(sid)
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_petname":
            toast(cq_id)
            set_state(chat_id, student_id=sid, pending={"action": "petname", "sid": sid})
            return edit(chat_id, message_id,
                        "✏️ Как назовём питомца? Пришлите имя одним сообщением.",
                        [[("⬅️ Назад", "lrn_pet:%d" % sid)]])
        if cmd == "lrn_next":
            toast(cq_id)
            return edit(chat_id, message_id, text_next_lesson(sid),
                        zoom_rows(sget(sid)) + [[("⬅️ Назад", "lrn:%d" % sid)]])
        if cmd == "lrn_mat":
            toast(cq_id)
            items = [m for m in materials_of(sid) if m["kind"] != "bonus"]
            rows = []
            for m in items:
                if m["kind"] == "link":
                    rows.append([("🌐 " + m["title"][:28], m["ref"])])
                else:
                    rows.append([("📄 " + m["title"][:28], "lrn_file:%d:%d" % (sid, m["id"]))])
            rows.append([("⬅️ Назад", "lrn:%d" % sid)])
            body = "📎 <b>Материалы</b>" if items else "📎 Материалов пока нет."
            return edit(chat_id, message_id, body, rows)
        if cmd == "lrn_file":
            toast(cq_id, "Отправляю файл")
            m = q("SELECT * FROM materials WHERE id=?", (int(parts[2]),), one=True)
            if m:
                send_file(chat_id, m["ref"], m["title"])
            return
        if cmd == "lrn_pay":
            toast(cq_id)
            st = stats(sid)
            return edit(chat_id, message_id,
                        "💳 <b>Оплата</b>\n\nОстаток занятий: <b>{}</b>\n"
                        "Реквизиты: {}\n\nПосле перевода просто напишите преподавателю.".format(
                            max(st["left"], 0), PAY_DETAILS),
                        [[("⬅️ Назад", "lrn:%d" % sid)]])
        if cmd == "lrn_fb":
            toast(cq_id)
            return edit(chat_id, message_id,
                        "💬 Как отправить отзыв о занятиях?",
                        [[("🙈 Анонимно", "fbr:%d:0" % sid)],
                         [("🙂 С моим именем", "fbr:%d:-1" % sid)],
                         [("⬅️ Назад", "lrn:%d" % sid)]])
        if cmd == "fbr":
            toast(cq_id)
            val = int(parts[2])
            if val > 0:
                set_state(chat_id, student_id=sid,
                          pending={"action": "fbstudent", "sid": sid, "rating": val, "anon": 1})
                return edit(chat_id, message_id,
                            "Спасибо! Оценка {}/5 записана.\n\nНапишите пару слов: "
                            "что было хорошо и что улучшить.".format(val),
                            [[("Пропустить", "fbskip:%d:%d" % (sid, val))]])
            set_state(chat_id, student_id=sid,
                      pending={"action": "fbstudent", "sid": sid, "rating": 0,
                               "anon": 1 if val == 0 else 0})
            return edit(chat_id, message_id, "Напишите отзыв одним сообщением.",
                        [[("⬅️ Назад", "lrn:%d" % sid)]])
        if cmd == "fbskip":
            toast(cq_id, "Спасибо!")
            save_feedback(sid, rating=int(parts[2]), text="", anon=1)
            set_state(chat_id, pending=None)
            t, r = screen_learner(sid)
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_key":
            toast(cq_id)
            s_ = sget(sid)
            bonus = q("SELECT * FROM materials WHERE kind='bonus' ORDER BY RANDOM() LIMIT 1",
                      one=True)
            if not s_["keys"]:
                return edit(chat_id, message_id, "🔑 Ключиков пока нет. "
                            "Они даются за повторение слов.", [[("⬅️ Назад", "lrn:%d" % sid)]])
            if not bonus:
                return edit(chat_id, message_id, "Бонусы пока не добавлены — ключик остался у вас.",
                            [[("⬅️ Назад", "lrn:%d" % sid)]])
            run("UPDATE students SET keys=keys-1 WHERE id=?", (sid,))
            if bonus["kind"] == "bonus" and str(bonus["ref"]).startswith("http"):
                rows = [[("🎁 " + bonus["title"][:28], bonus["ref"])],
                        [("⬅️ Назад", "lrn:%d" % sid)]]
                return edit(chat_id, message_id, "🎁 Бонус открыт!", rows)
            send_file(chat_id, bonus["ref"], bonus["title"])
            t, r = screen_learner(sid)
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_when":
            toast(cq_id)
            return edit(chat_id, message_id, text_when(sid),
                        [[("⬅️ Назад", "lrn:%d" % sid)]])
        if cmd == "lw":
            toast(cq_id)
            t, r = screen_wpick(sid, learner=True)
            return edit(chat_id, message_id, t, r)
        if cmd == "lw_back":
            toast(cq_id)
            t, r = screen_learner(sid)
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_prog":
            toast(cq_id)
            s_ = sget(sid)
            if s_["is_guest"]:
                nick_row = [("🎲 Другой ник: {}".format(nick_of(s_)), "lrn_renick:%d" % sid)]
            else:
                nick_row = [("✏️ Ник для рейтинга: {}".format(nick_of(s_)), "lrn_nick:%d" % sid)]
            return edit(chat_id, message_id, text_progress(sid, own=True),
                        [[("🏆 Рейтинг", "lrn_board:%d" % sid)], nick_row,
                         [("⬅️ Назад", "lrn:%d" % sid)]])
        if cmd == "lrn_renick":
            nick = gen_nick(sget(sid)["chat_id"])
            run("UPDATE students SET nick=? WHERE id=?", (nick, sid))
            toast(cq_id, "Теперь вы " + nick)
            return edit(chat_id, message_id, text_progress(sid, own=True),
                        [[("🏆 Рейтинг", "lrn_board:%d" % sid)],
                         [("🎲 Другой ник: {}".format(nick), "lrn_renick:%d" % sid)],
                         [("⬅️ Назад", "lrn:%d" % sid)]])
        if cmd == "lrn_board":
            toast(cq_id)
            s_ = sget(sid)
            t, r = screen_board(s_["chat_id"], me_sid=sid, real_names=False)
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_nick":
            toast(cq_id)
            if sget(sid)["is_guest"]:
                nick = gen_nick(sget(sid)["chat_id"])
                run("UPDATE students SET nick=? WHERE id=?", (nick, sid))
                return edit(chat_id, message_id, text_progress(sid, own=True),
                            [[("⬅️ Назад", "lrn:%d" % sid)]])
            set_state(chat_id, student_id=sid, pending={"action": "nick", "sid": sid})
            return edit(chat_id, message_id,
                        "✏️ Придумайте ник для рейтинга — его видят другие ученики "
                        "вместо вашего имени. Напишите его сообщением.",
                        [[("⬅️ Назад", "lrn:%d" % sid)]])
        if cmd == "lrn_promo":
            toast(cq_id)
            send(chat_id, text_share_bot())
            t, r = screen_learner(sid)
            return edit(chat_id, message_id,
                        "💌 Сообщение о занятиях отправлено ниже — перешлите его "
                        "тому, кому может быть интересно.\n\n" + t, r)
        if cmd == "lwdl":
            w = q("SELECT * FROM words WHERE id=?", (int(parts[2]),), one=True)
            if w and w["student_id"] == sid:
                run("DELETE FROM words WHERE id=?", (w["id"],))
                toast(cq_id, "Удалено: " + w["term"])
            else:
                toast(cq_id)
            t, r = screen_wpick(sid, learner=True)
            return edit(chat_id, message_id, t, r)
        if cmd == "w_show":
            toast(cq_id)
            w = q("SELECT * FROM words WHERE id=?", (int(parts[2]),), one=True)
            t, r = screen_card(sid, w, show=True)
            return edit(chat_id, message_id, t, r)
        if cmd == "w_del":
            toast(cq_id)
            w = q("SELECT * FROM words WHERE id=?", (int(parts[2]),), one=True)
            if not w:
                return toast(cq_id, "Слово уже удалено")
            t, r = screen_card_del(sid, w)
            return edit(chat_id, message_id, t, r)
        if cmd == "w_delok":
            wid = int(parts[2])
            w = q("SELECT * FROM words WHERE id=?", (wid,), one=True)
            run("DELETE FROM reviews WHERE word_id=?", (wid,))
            run("DELETE FROM words WHERE id=?", (wid,))
            toast(cq_id, "Удалено: {}".format(w["term"][:30]) if w else "Удалено")
            ws = due_words(sid, 1)
            t, r = screen_card(sid, ws[0] if ws else None)
            return edit(chat_id, message_id,
                        "🗑 Слово <b>{}</b> удалено.\n\n".format(esc(w["term"])) + t
                        if w else t, r)
        if cmd == "w_g":
            ivl = grade_word(int(parts[2]), int(parts[3]))
            toast(cq_id, "Следующий повтор: " + ivl_label(ivl or 0))
            ws = due_words(sid, 1)
            t, r = screen_card(sid, ws[0] if ws else None)
            return edit(chat_id, message_id, t, r)

    if not is_owner(user_id):
        return toast(cq_id, "Эта кнопка только для преподавателя")

    toast(cq_id)

    def show(fn, *a):
        t, r = fn(*a)
        edit(chat_id, message_id, t, r)

    if cmd.startswith(("fin_", "cr_", "money", "nt_", "notes", "bks_", "bka", "books")):
        sid = None
    if sid is not None and not student(sid):
        t, r = screen_students(chat_id)
        return edit(chat_id, message_id,
                    "⚠️ Такого ученика в базе нет. Скорее всего, это кнопка из старой "
                    "карточки, а база была очищена при перезапуске.\n\n" + t, r)

    if cmd == "menu":
        set_state(chat_id, student_id=None, pending=None)
        return show(screen_students, chat_id)
    if cmd == "month":
        return show(screen_month, chat_id)
    if cmd == "week":
        return show(screen_week, chat_id)
    if cmd == "sched_all":
        return show(screen_schedule_all, chat_id)
    if cmd == "arch_list":
        return show(screen_archive, chat_id)
    if cmd == "export":
        return export_csv(chat_id)

    if cmd == "new":
        set_state(chat_id, pending={"action": "new_student"})
        return edit(chat_id, message_id, "Как зовут ученика? Напишите имя сообщением.",
                    [[("⬅️ Отмена", "menu")]])

    if cmd == "st":
        set_state(chat_id, student_id=sid, pending=None)
        return show(screen_student, sid)

    if cmd == "done":
        lid = record_lesson(chat_id, sid, today())
        b = book_of(sid)
        if b:
            s_ = sget(sid)
            flat = [(u["n"], l["n"]) for u in b["units"] for l in u["lessons"]]
            try:
                i = flat.index((s_["unit"] or 1, s_["lesson"] or 1))
            except ValueError:
                i = -1
            if 0 <= i < len(flat) - 1:
                run("UPDATE students SET unit=?, lesson=? WHERE id=?",
                    (flat[i + 1][0], flat[i + 1][1], sid))
        return edit(chat_id, message_id, *screen_after(sid, lid))

    if cmd == "after":
        return edit(chat_id, message_id, *screen_after(sid, int(parts[2])))

    if cmd == "afterhw":
        set_state(chat_id, student_id=sid,
                  pending={"action": "hw", "sid": sid, "lid": int(parts[2]), "after": 1})
        nxt = next_lesson_date(sid)
        return edit(chat_id, message_id,
                    "📝 Что задать на дом{}?\nПришлите текст — ученик получит его сразу."
                    .format(" к занятию " + fmt_date(nxt) if nxt else ""),
                    [[("⬅️ Пропустить", "after:%d:%s" % (sid, parts[2]))]])

    if cmd == "afterw":
        set_state(chat_id, student_id=sid,
                  pending={"action": "words", "sid": sid, "by": "педагог",
                           "lid": int(parts[2]), "after": 1})
        return edit(chat_id, message_id,
                    "📚 Какие слова с занятия добавить? По одному в строке, можно без "
                    "перевода — оформлю сама.\n\n<code>coerce - принуждать\nreluctant</code>",
                    [[("⬅️ Пропустить", "after:%d:%s" % (sid, parts[2]))]])

    if cmd == "doned":
        set_state(chat_id, student_id=sid, pending={"action": "lesson_date", "sid": sid})
        return edit(chat_id, message_id, "Какой датой записать занятие?\nНапример: 15.09 или вчера",
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "note":
        set_state(chat_id, student_id=sid,
                  pending={"action": "note", "sid": sid, "lid": int(parts[2])})
        return edit(chat_id, message_id, "✍️ Что прошли на занятии? Одной строкой.",
                    [[("⬅️ Пропустить", "after:%d:%s" % (sid, parts[2]))]])

    if cmd == "cancel":
        rows = [[("Списать занятие", "canc1:%d" % sid)],
                [("Без списания", "canc0:%d" % sid)],
                [("⬅️ Назад", "st:%d" % sid)]]
        return edit(chat_id, message_id, "🚫 Отмена занятия сегодня.\nСписывать его с пакета?", rows)

    if cmd in ("canc1", "canc0"):
        charged = 1 if cmd == "canc1" else 0
        rows = [[(r, "cancr:%d:%d:%d" % (sid, charged, i))]
                for i, r in enumerate(CANCEL_REASONS)]
        rows.append([("⬅️ Назад", "st:%d" % sid)])
        return edit(chat_id, message_id, "🚫 Причина отмены? (видно только вам)", rows)

    if cmd == "cancr":
        charged, idx = int(parts[2]), int(parts[3])
        reason = CANCEL_REASONS[idx] if idx < len(CANCEL_REASONS) else ""
        if reason == "другое":
            set_state(chat_id, student_id=sid,
                      pending={"action": "cancel_reason", "sid": sid, "charged": charged})
            return edit(chat_id, message_id, "Напишите причину отмены одной строкой.",
                        [[("⬅️ Назад", "st:%d" % sid)]])
        record_lesson(chat_id, sid, today(), kind="cancel", charged=charged, reason=reason)
        return show(screen_student, sid)

    if cmd == "move":
        return show(screen_move, sid)

    if cmd == "mv":
        set_state(chat_id, student_id=sid,
                  pending={"action": "move_to", "sid": sid, "from": parts[2]})
        return edit(chat_id, message_id,
                    "🔁 Переносим занятие {}.\nНа какую дату и время?\n"
                    "Например: <code>20.09 17:00</code>".format(fmt_date(parts[2])),
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "undo":
        last = q("SELECT * FROM lessons WHERE student_id=? ORDER BY id DESC LIMIT 1", (sid,), one=True)
        if last:
            run("DELETE FROM lessons WHERE id=?", (last["id"],))
            flash(chat_id, "↩️ Запись от {} удалена. Остаток: <b>{}</b>.".format(
                fmt_date(last["held_on"]), stats(sid)["left"]))
        else:
            send(chat_id, "Записей нет.")
        return show(screen_student, sid)

    if cmd == "undopay":
        last = q("SELECT * FROM payments WHERE student_id=? ORDER BY id DESC LIMIT 1", (sid,), one=True)
        if last:
            run("DELETE FROM payments WHERE id=?", (last["id"],))
            flash(chat_id, "↩️ Оплата {} удалена. Остаток: <b>{}</b>.".format(
                fmt_money(last["amount"]), stats(sid)["left"]))
        else:
            send(chat_id, "Оплат нет.")
        return show(screen_student, sid)

    if cmd == "pay":
        return show(screen_pay, sid)

    if cmd == "payn":
        n = int(parts[2])
        s = sget(sid)
        if s["rate"]:
            run("INSERT INTO payments (student_id, lessons, amount, paid_on) VALUES (?,?,?,?)",
                (sid, n, n * s["rate"], today().isoformat()))
            fin_income(n * s["rate"], "Оплата: " + s["name"])
            flash(chat_id, "✅ Оплата — <b>{}</b>: {} {} · {} · {}.\nОстаток: <b>{}</b>.".format(
                esc(s["name"]), n, plural(n), fmt_money(n * s["rate"]), fmt_date(today()),
                stats(sid)["left"]))
            return show(screen_student, sid)
        set_state(chat_id, student_id=sid, pending={"action": "amount", "sid": sid, "lessons": n})
        return edit(chat_id, message_id,
                    "Пакет {} зан.\nНапишите сумму, можно с датой и ссылкой на чек:\n"
                    "<code>4000 12.09 https://…</code>\nБез суммы — «-».".format(n),
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "payc":
        set_state(chat_id, student_id=sid, pending={"action": "custom_lessons", "sid": sid})
        return edit(chat_id, message_id, "Сколько занятий в пакете? Напишите число.",
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "sched":
        return show(screen_sched, sid)

    if cmd == "schedc":
        set_state(chat_id, student_id=sid, pending={"action": "schedule", "sid": sid})
        cur = slots_text(sid)
        return edit(chat_id, message_id,
                    "🔁 <b>Постоянное расписание</b>{}\n\nНапишите дни и время:\n"
                    "<code>пн 17:00, чт 18:30</code>\nОчистить — «-».".format(
                        "\nСейчас: " + cur if cur else ""),
                    [[("⬅️ Назад", "sched:%d" % sid)]])

    if cmd == "appt":
        set_state(chat_id, student_id=sid, pending={"action": "dates", "sid": sid})
        return edit(chat_id, message_id,
                    "📌 <b>Разовые даты</b>\n\nНапишите даты и время через запятую:\n"
                    "<code>22.09 17:00, 25.09 12:00</code>\n\n"
                    "Они добавятся к уже назначенным.",
                    [[("⬅️ Назад", "sched:%d" % sid)]])

    if cmd == "apptdel":
        n = len(q("SELECT id FROM appts WHERE student_id=? AND on_date>=?",
                  (sid, today().isoformat())))
        run("DELETE FROM appts WHERE student_id=? AND on_date>=?", (sid, today().isoformat()))
        flash(chat_id, "🧹 Убрано разовых дат: <b>{}</b>.".format(n))
        return show(screen_sched, sid)

    if cmd == "hist":
        return show(screen_history, sid)

    if cmd == "notes":
        t, r = screen_notes(chat_id)
        return edit(chat_id, message_id, t, r)

    if cmd == "nt_add":
        set_state(chat_id, pending={"action": "note_text"})
        return edit(chat_id, message_id,
                    "⏰ Напишите заметку и когда напомнить — одним сообщением.\n\n"
                    "<code>завтра в 10 позвонить в клинику</code>\n"
                    "<code>через 2 часа проверить тесты</code>\n"
                    "<code>25.09 18:00 оплатить кредит</code>\n"
                    "<code>каждый понедельник в 9 выставить счета</code>\n\n"
                    "Можно прислать файл или ссылку с такой же подписью.",
                    [[("⬅️ Назад", "notes")]])

    if cmd == "nt_item":
        r_ = q("SELECT * FROM notes WHERE id=?", (int(parts[1]),), one=True)
        if not r_:
            t, r = screen_notes(chat_id)
            return edit(chat_id, message_id, t, r)
        return edit(chat_id, message_id,
                    "⏰ <b>{}</b>\n\n{}{}".format(
                        fmt_when(r_["due"]), esc(r_["text"] or ""),
                        "\n📎 " + esc(r_["file_name"] or "файл") if r_["file_id"] else ""),
                    [[("✅ Выполнено", "nt_done:%d" % r_["id"]),
                      ("🗑 Удалить", "nt_del:%d" % r_["id"])],
                     [("🔁 Через час", "nt_snooze:%d" % r_["id"]),
                      ("📅 Завтра", "nt_tom:%d" % r_["id"])],
                     [("⬅️ Назад", "notes")]])

    if cmd in ("nt_done", "nt_del"):
        if cmd == "nt_done":
            run("UPDATE notes SET done=1 WHERE id=?", (int(parts[1]),))
        else:
            run("DELETE FROM notes WHERE id=?", (int(parts[1]),))
        toast(cq_id, "Готово")
        t, r = screen_notes(chat_id)
        return edit(chat_id, message_id, t, r)

    if cmd in ("nt_snooze", "nt_tom"):
        when = (datetime.now() + timedelta(hours=1)) if cmd == "nt_snooze" else \
            datetime.combine(today() + timedelta(days=1), dtime(9, 0))
        run("UPDATE notes SET due=?, done=0 WHERE id=?",
            (when.isoformat(timespec="minutes"), int(parts[1])))
        toast(cq_id, "Перенесла")
        t, r = screen_notes(chat_id)
        return edit(chat_id, message_id, t, r)

    if cmd == "money":
        t, r = screen_money()
        return edit(chat_id, message_id, t, r)

    if cmd == "cr_list":
        t, r = screen_credits()
        return edit(chat_id, message_id, t, r)

    if cmd == "cr_add":
        set_state(chat_id, pending={"action": "credit"})
        return edit(chat_id, message_id,
                    "💳 Пришлите одной строкой: <b>название, остаток, ставка, "
                    "минимальный платёж</b> — и, если есть, комиссия.\n\n"
                    "<code>Тинькофф, 350000, 25.9, 12000</code>\n"
                    "<code>Сбер, 120000, 19.5, 6000, 590</code>",
                    [[("⬅️ Назад", "cr_list")]])

    if cmd == "cr_pay":
        set_state(chat_id, pending={"action": "credit_pay", "cid": int(parts[1])})
        c = q("SELECT * FROM credits WHERE id=?", (int(parts[1]),), one=True)
        return edit(chat_id, message_id,
                    "💸 Сколько внесли по «{}»? Остаток сейчас {}.".format(
                        esc(c["name"]), money(c["balance"] or 0)),
                    [[("⬅️ Назад", "cr_list")]])

    if cmd == "cr_del":
        run("DELETE FROM credits WHERE id=?", (int(parts[1]),))
        toast(cq_id, "Удалено")
        t, r = screen_credits()
        return edit(chat_id, message_id, t, r)

    if cmd == "fin_day":
        t, r = screen_fin_day()
        return edit(chat_id, message_id, t, r)

    if cmd == "fin_item":
        t, r = screen_fin_item(int(parts[1]))
        return edit(chat_id, message_id, t, r)

    if cmd == "fin_cat":
        tid, cat = int(parts[1]), parts[2]
        r_ = q("SELECT * FROM fin_tx WHERE id=?", (tid,), one=True)
        if r_:
            run("UPDATE fin_tx SET category=? WHERE id=?", (cat, tid))
            run("INSERT OR REPLACE INTO fin_cat (merchant, category) VALUES (?,?)",
                (r_["title"].strip().lower(), cat))
        toast(cq_id, "Категория: " + cat)
        t, r = screen_fin_day()
        return edit(chat_id, message_id, t, r)

    if cmd == "fin_del":
        run("DELETE FROM fin_tx WHERE id=?", (int(parts[1]),))
        toast(cq_id, "Удалено")
        t, r = screen_fin_day()
        return edit(chat_id, message_id, t, r)

    if cmd == "fin_new":
        kind = "i" if parts[1] == "i" else "e"
        set_state(chat_id, pending={"action": "fin_new", "kind": kind})
        return edit(chat_id, message_id,
                    "➕ Пришлите {}, по одной в строке:\n\n<code>{}</code>".format(
                        "поступления" if kind == "i" else "траты",
                        "занятие Аня 2500\nвозврат 900" if kind == "i"
                        else "пятёрочка 1200\nцппк 250"),
                    [[("⬅️ Назад", "money")]])

    if cmd == "cr_edit":
        c = q("SELECT * FROM credits WHERE id=?", (int(parts[1]),), one=True)
        set_state(chat_id, pending={"action": "credit", "cid": c["id"]})
        return edit(chat_id, message_id,
                    "✏️ Пришлите новые данные одной строкой:\n\n"
                    "<code>{}, {:.0f}, {}, {:.0f}{}</code>".format(
                        c["name"], c["balance"] or 0, c["rate"] or 0, c["min_pay"] or 0,
                        ", {:.0f}".format(c["fee"]) if c["fee"] else ""),
                    [[("⬅️ Назад", "cr_list")]])

    if cmd == "fin_none":
        toast(cq_id, "Записала")
        return edit(chat_id, message_id, "👌 День без трат — отметила.", [])

    if cmd == "fin_month":
        inc, exp, cats = fin_month()
        lines = ["📊 <b>Месяц</b>", "", "Поступления: {}".format(money(inc)),
                 "Траты: {}".format(money(exp)), ""]
        for name, s_, c in cats:
            lines.append("• {} — {} ({})".format(name, money(s_), c))
        return edit(chat_id, message_id, "\n".join(lines), [[("⬅️ Назад", "money")]])

    if cmd == "fin_csv":
        rows_ = q("SELECT on_date, kind, amount, title, category FROM fin_tx "
                  "ORDER BY on_date DESC, id DESC")
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["дата", "тип", "сумма", "название", "категория"])
        for r_ in rows_:
            w.writerow([r_["on_date"], "доход" if r_["kind"] == "income" else "трата",
                        r_["amount"], r_["title"], r_["category"]])
        send_document(chat_id, "money_{}.csv".format(today().isoformat()), buf.getvalue(),
                      "Все траты и поступления")
        return toast(cq_id, "Отправила")

    if cmd == "wundo":
        ids = [int(x) for x in parts[1].split(",") if x.isdigit()]
        for wid in ids:
            run("DELETE FROM reviews WHERE word_id=?", (wid,))
            run("DELETE FROM words WHERE id=?", (wid,))
        toast(cq_id, "Убрано")
        return edit(chat_id, message_id, "↩️ Убрала {} {} из словаря.".format(
            len(ids), plural(len(ids), ("слово", "слова", "слов"))), [])

    if cmd == "myw":
        me = self_student(chat_id, user_id)
        set_state(chat_id, pending=None)
        t, r = screen_learner(me["id"])
        return edit(chat_id, message_id, t, r)

    if cmd == "rawlist":
        return show(screen_raw, sid)

    if cmd == "rawadd":
        set_state(chat_id, student_id=sid, pending={"action": "rawadd", "sid": sid})
        return edit(chat_id, message_id,
                    "🧺 Пришлите слова по одному в строке — можно только по-английски "
                    "или только по-русски, без перевода.",
                    [[("⬅️ Назад", "rawlist:%d" % sid)]])

    if cmd == "rawfix":
        items = raw_words(sid)
        set_state(chat_id, student_id=sid, pending={"action": "rawfix", "sid": sid})
        body = ", ".join(w["term"] for w in items[:30])
        return edit(chat_id, message_id,
                    "✍️ Пришлите пары <code>слово - перевод</code>, по одной в строке.\n"
                    "Совпавшие сырые слова станут обычными.\n\nСейчас в корзине:\n" + esc(body),
                    [[("⬅️ Назад", "rawlist:%d" % sid)]])

    if cmd == "rawai":
        toast(cq_id, "Оформляю, это займёт несколько секунд")
        edit(chat_id, message_id, "✨ Оформляю карточки через ИИ…", [])
        done, why = ai_format_raw(sid)
        if not done:
            flash(chat_id, "⚠️ " + (why or "Не получилось."))
        else:
            flash(chat_id, "✅ Оформлено карточек: {}.".format(done))
            w = q("SELECT * FROM words WHERE student_id=? AND COALESCE(raw,0)=0 "
                  "ORDER BY id DESC LIMIT 1", (sid,), one=True)
            if w:
                send(chat_id, "Пример:\n\n" + card_back(w))
        return show(screen_raw, sid)

    if cmd == "rawclear":
        run("DELETE FROM words WHERE student_id=? AND raw=1", (sid,))
        flash(chat_id, "🧹 Сырые слова очищены.")
        return show(screen_raw, sid)

    if cmd == "hw":
        return show(screen_hw, sid)

    if cmd == "hwadd":
        set_state(chat_id, student_id=sid, pending={"action": "hw", "sid": sid})
        nxt = next_lesson_date(sid)
        return edit(chat_id, message_id,
                    "📝 Напишите домашнее задание{}.\nМожно с ссылками — ученик получит "
                    "его сразу, если подключён к боту.".format(
                        " к занятию " + fmt_date(nxt) if nxt else
                        " (дата следующего занятия не назначена)"),
                    [[("⬅️ Назад", "hw:%d" % sid)]])

    if cmd == "hwdone":
        run("UPDATE homework SET done=1 WHERE student_id=? AND done=0", (sid,))
        flash(chat_id, "✅ Задание снято.")
        return show(screen_hw, sid)

    if cmd == "mat":
        return show(screen_mat, sid)

    if cmd == "matdel":
        return show(screen_matdel, sid)

    if cmd == "matrm":
        run("DELETE FROM materials WHERE id=?", (int(parts[2]),))
        flash(chat_id, "🗑 Материал удалён.")
        return show(screen_mat, sid)

    if cmd in ("matlink", "matbonus"):
        kind = "link" if cmd == "matlink" else "bonus"
        set_state(chat_id, student_id=sid, pending={"action": "material", "sid": sid, "kind": kind})
        extra = ("\n\nБонус видят ученики, которые потратили ключик."
                 if kind == "bonus" else "")
        return edit(chat_id, message_id,
                    "🌐 Пришлите ссылку. Можно с названием:\n"
                    "<code>Учебник Evolve 5 — https://drive.google.com/…</code>"
                    "\n\nЧтобы материал был общим для всех учеников, начните строку "
                    "со слова <code>всем</code>." + extra,
                    [[("⬅️ Назад", "mat:%d" % sid)]])

    if cmd == "matfile":
        set_state(chat_id, student_id=sid, pending={"action": "matfile", "sid": sid})
        return edit(chat_id, message_id,
                    "📄 Пришлите файл (PDF, docx и т. п.) обычным сообщением — "
                    "я сохраню его и смогу отправлять ученику.",
                    [[("⬅️ Назад", "mat:%d" % sid)]])

    if cmd == "fb":
        return show(screen_fb, sid)

    if cmd == "fbwrite":
        set_state(chat_id, student_id=sid, pending={"action": "fbteacher", "sid": sid})
        return edit(chat_id, message_id, "✍️ Напишите отзыв ученику — он получит его в бот.",
                    [[("⬅️ Назад", "fb:%d" % sid)]])

    if cmd == "fbask":
        if ask_feedback(sid):
            flash(chat_id, "📨 Запрос оценки отправлен ученику.")
        else:
            flash(chat_id, "Ученик не подключён к боту — запрос отправить некуда.")
        return show(screen_fb, sid)

    if cmd.startswith(("hwd", "bk_")) and not book_of(sid) and cmd not in ("bk_set",):
        t, r = screen_book(sid)
        return edit(chat_id, message_id, t, r)

    if cmd == "hwd":
        t, r = screen_hw_draft(sid)
        return edit(chat_id, message_id, t, r)

    if cmd == "hwd_gen":
        edit(chat_id, message_id, "🤖 Собираю домашку по уроку…", [])
        body, prompt, cached = ai_book_material(sid, "hw")
        if not body:
            t, r = screen_hw_draft(sid)
            return edit(chat_id, message_id, "⚠️ ИИ не ответил.\n\n" + t, r)
        b = book_of(sid)
        s_ = sget(sid)
        l = lesson_of(b, s_["unit"] or 1, s_["lesson"] or 1)
        draft_put(sid, b["id"], l["code"], text=body)
        t, r = screen_hw_draft(sid)
        return edit(chat_id, message_id, t, r)

    if cmd in ("hwd_edit", "hwd_add"):
        set_state(chat_id, student_id=sid,
                  pending={"action": "hwdraft", "sid": sid,
                           "mode": "set" if cmd == "hwd_edit" else "add"})
        return edit(chat_id, message_id,
                    "✏️ Пришлите текст домашки — {}.".format(
                        "он заменит нынешний" if cmd == "hwd_edit" else "допишу к нынешнему"),
                    [[("⬅️ Назад", "hwd:%d" % sid)]])

    if cmd == "hwd_voc":
        words = unit_target_words(sid)
        if not words:
            return toast(cq_id, "У юнита нет списка слов")
        b = book_of(sid)
        s_ = sget(sid)
        l = lesson_of(b, s_["unit"] or 1, s_["lesson"] or 1)
        d = draft_get(sid, b["id"], l["code"])
        block = "\n\nTarget vocabulary: " + ", ".join(words)
        draft_put(sid, b["id"], l["code"], text=((d["text"] if d else "") or "") + block)
        toast(cq_id, "Добавила {} слов".format(len(words)))
        t, r = screen_hw_draft(sid)
        return edit(chat_id, message_id, t, r)

    if cmd == "hwd_audio":
        t, r = screen_hw_audio(sid)
        return edit(chat_id, message_id, t, r)

    if cmd == "hwd_atog":
        b = book_of(sid)
        s_ = sget(sid)
        l = lesson_of(b, s_["unit"] or 1, s_["lesson"] or 1)
        d = draft_put(sid, b["id"], l["code"])
        ids = [x for x in (d["audio"] or "").split(",") if x.strip().isdigit()]
        tid = parts[2]
        ids = [x for x in ids if x != tid] if tid in ids else ids + [tid]
        run("UPDATE hw_draft SET audio=? WHERE id=?", (",".join(ids), d["id"]))
        toast(cq_id)
        t, r = screen_hw_audio(sid)
        return edit(chat_id, message_id, t, r)

    if cmd == "hwd_send":
        b = book_of(sid)
        s_ = sget(sid)
        l = lesson_of(b, s_["unit"] or 1, s_["lesson"] or 1)
        d = draft_get(sid, b["id"], l["code"])
        if not d or not (d["text"] or "").strip():
            return toast(cq_id, "Сначала наполните домашку")
        nxt = next_lesson_date(sid)
        run("INSERT INTO homework (student_id, text, due, created, done) VALUES (?,?,?,?,0)",
            (sid, d["text"][:1500], nxt.isoformat() if nxt else None, today().isoformat()))
        sent = notify_student(sid, "📝 <b>Homework</b>{}\n\n{}".format(
            " for " + fmt_date(nxt) if nxt else "", esc(d["text"][:1500])))
        ids = [int(x) for x in (d["audio"] or "").split(",") if x.strip().isdigit()]
        st = sget(sid)
        for tid in ids:
            t_ = q("SELECT * FROM audio WHERE id=?", (tid,), one=True)
            if t_ and st["tg_user_id"]:
                cap = "{} {}".format(b["title"], l["code"])
                if t_["task"]:
                    cap += "\n" + t_["task"][:900]
                tg("sendAudio", chat_id=st["tg_user_id"], audio=t_["file_id"],
                   caption=cap[:1000])
        toast(cq_id, "Отправлено" if sent else "Сохранено (ученик не подключён)")
        t, r = screen_hw_draft(sid)
        return edit(chat_id, message_id, t, r)

    if cmd == "books":
        t, r = screen_books()
        return edit(chat_id, message_id, t, r)

    if cmd == "bks_open":
        t, r = screen_book_admin(parts[1])
        return edit(chat_id, message_id, t, r)

    if cmd == "bks_units":
        t, r = screen_book_units(parts[1], int(parts[2]))
        return edit(chat_id, message_id, t, r)

    if cmd == "bks_les":
        t, r = screen_book_lessons(parts[1], int(parts[2]), int(parts[3]))
        return edit(chat_id, message_id, t, r)

    if cmd == "bks_min":
        set_state(chat_id, pending={"action": "bookfield", "bid": parts[1],
                                    "field": "lesson_minutes"})
        return edit(chat_id, message_id, "⏱ Сколько минут длится занятие? Пришлите число.",
                    [[("⬅️ Назад", "bks_open:%s" % parts[1])]])

    if cmd == "bks_del":
        b = BOOKS.get(parts[1])
        run("DELETE FROM books WHERE id=?", (parts[1],))
        run("UPDATE students SET book=NULL WHERE book=?", (parts[1],))
        load_books()
        toast(cq_id, "Удалён")
        t, r = screen_books()
        return edit(chat_id, message_id,
                    ("🗑 «{}» убран из бота.\n\n".format(esc(b["title"])) if b else "") + t, r)

    if cmd in ("bks_wl", "bks_wladd"):
        set_state(chat_id, pending={"action": "wordlist", "bid": parts[1],
                                    "unit": int(parts[2]), "mode": cmd})
        return edit(chat_id, message_id,
                    "📚 Пришлите слова юнита через запятую или по одному в строке.\n"
                    "{}".format("Старый список заменю." if cmd == "bks_wl"
                                else "Допишу к тому, что есть."),
                    [[("⬅️ Назад", "bks_units:%s:%d" % (parts[1], int(parts[2])))]])

    if cmd == "bks_f":
        set_state(chat_id, pending={"action": "lessonfield", "bid": parts[1],
                                    "unit": int(parts[2]), "lesson": int(parts[3]),
                                    "field": parts[4]})
        l = lesson_of(BOOKS[parts[1]], int(parts[2]), int(parts[3]))
        return edit(chat_id, message_id,
                    "✏️ Сейчас: <code>{}</code>\n\nПришлите новый текст.".format(
                        esc(str(l.get(parts[4], "—")))),
                    [[("⬅️ Назад", "bks_les:%s:%d:%d" % (parts[1], int(parts[2]),
                                                        int(parts[3])))]])

    if cmd == "bka_book":
        t, r = screen_audio_book(parts[1])
        return edit(chat_id, message_id, t, r)

    if cmd == "bka_item":
        t, r = screen_audio_item(int(parts[1]))
        return edit(chat_id, message_id, t, r)

    if cmd == "bka_gen":
        edit(chat_id, message_id, "🤖 Придумываю задание к записи…", [])
        ok_ = ai_audio_task(int(parts[1]))
        t, r = screen_audio_item(int(parts[1]))
        return edit(chat_id, message_id,
                    ("" if ok_ else "⚠️ ИИ не ответил или у трека нет урока.\n\n") + t, r)

    if cmd in ("bka_task", "bka_ans"):
        set_state(chat_id, pending={"action": "audiofield", "tid": int(parts[1]),
                                    "field": "task" if cmd == "bka_task" else "answers"})
        return edit(chat_id, message_id,
                    "✏️ Пришлите {} для этой записи.".format(
                        "задание — его увидит ученик" if cmd == "bka_task"
                        else "ключи — они останутся только у вас"),
                    [[("⬅️ Назад", "bka_item:%s" % parts[1])]])

    if cmd == "bka_move":
        set_state(chat_id, pending={"action": "audiomove", "tid": int(parts[1])})
        return edit(chat_id, message_id,
                    "📍 В какой урок перенести? Пришлите код, например <code>3.2</code>.",
                    [[("⬅️ Назад", "bka_item:%s" % parts[1])]])

    if cmd == "bka_sort":
        moved = audio_resort(parts[1])
        toast(cq_id, "Переложено: {}".format(moved))
        t, r = screen_audio_book(parts[1])
        return edit(chat_id, message_id, "🔄 Переложено треков: {}\n\n".format(moved) + t, r)

    if cmd == "bka_dedup":
        killed = audio_dedupe(parts[1])
        toast(cq_id, "Удалено дублей: {}".format(killed))
        t, r = screen_audio_book(parts[1])
        return edit(chat_id, message_id, "🧹 Убрано дублей: {}\n\n".format(killed) + t, r)

    if cmd == "bka_bulk":
        set_state(chat_id, pending={"action": "audio_book", "book": parts[1]})
        return edit(chat_id, message_id,
                    "🎧 Присылайте аудио пачкой — я разложу по урокам сама.\n\n"
                    "Понимаю имена вида <code>1.08</code>, <code>Unit 3 Track 2</code>, "
                    "<code>WB 3.2</code>, <code>PB_1.3</code>. Что не разберу — сложу "
                    "отдельно и спрошу.",
                    [[("✅ Готово", "bka_book:%s" % parts[1])]])

    if cmd == "bka_fix":
        set_state(chat_id, pending={"action": "audio_fix", "book": parts[1]})
        t, r = screen_audio_fix(parts[1])
        return edit(chat_id, message_id, t, r)

    if cmd == "bka":
        t, r = screen_lesson_audio(parts[1], int(parts[2]), int(parts[3]))
        return edit(chat_id, message_id, t, r)

    if cmd == "bka_add":
        l = lesson_of(BOOKS[parts[1]], int(parts[2]), int(parts[3]))
        set_state(chat_id, pending={"action": "audio", "book": parts[1], "code": l["code"],
                                    "unit": int(parts[2]), "lesson": int(parts[3])})
        return edit(chat_id, message_id,
                    "🎧 Пришлите аудиофайл для урока {}. Можно несколько подряд — "
                    "каждый следующий тоже привяжу к этому уроку.".format(l["code"]),
                    [[("⬅️ Назад", "bka:%s:%d:%d" % (parts[1], int(parts[2]),
                                                    int(parts[3])))]])

    if cmd == "bka_del":
        t = q("SELECT * FROM audio WHERE id=?", (int(parts[1]),), one=True)
        run("DELETE FROM audio WHERE id=?", (int(parts[1]),))
        toast(cq_id, "Удалено")
        if not t:
            return
        b = BOOKS.get(t["book"])
        u = next((u["n"] for u in b["units"] for l in u["lessons"]
                  if l["code"] == t["code"]), 1) if b else 1
        l = next((l["n"] for uu in b["units"] for l in uu["lessons"]
                  if l["code"] == t["code"]), 1) if b else 1
        tt, r = screen_lesson_audio(t["book"], u, l)
        return edit(chat_id, message_id, tt, r)

    if cmd == "bka_send":
        t = q("SELECT * FROM audio WHERE id=?", (int(parts[1]),), one=True)
        if not t:
            return toast(cq_id, "Файл не найден")
        cap = "{} · {}".format(BOOKS.get(t["book"], {}).get("title", ""), t["code"])
        if t["task"]:
            cap += "\n" + t["task"][:500]
        tg("sendAudio", chat_id=chat_id, audio=t["file_id"], caption=cap[:1000])
        return toast(cq_id, "Отправила")

    if cmd == "book":
        return show(screen_book, sid)

    if cmd == "bk_set":
        b = BOOKS.get(parts[2])
        run("UPDATE students SET book=?, unit=COALESCE(unit,1), lesson=COALESCE(lesson,1) "
            "WHERE id=?", (parts[2], sid))
        if b and b.get("level") and not sget(sid)["level"]:
            run("UPDATE students SET level=? WHERE id=?", (b["level"].split()[0], sid))
        toast(cq_id, "Учебник выбран")
        return show(screen_book, sid)

    if cmd == "bk_reset":
        run("UPDATE students SET book=NULL WHERE id=?", (sid,))
        return show(screen_book, sid)

    if cmd == "bk_pick":
        t, r = screen_book_pick(sid, int(parts[2]))
        return edit(chat_id, message_id, t, r)

    if cmd == "bk_lset":
        run("UPDATE students SET unit=?, lesson=? WHERE id=?",
            (int(parts[2]), int(parts[3]), sid))
        toast(cq_id, "Урок выбран")
        return show(screen_book, sid)

    if cmd in ("bk_next", "bk_prev"):
        b = book_of(sid)
        if not b:
            return toast(cq_id, "Учебник не выбран")
        s_ = sget(sid)
        flat = [(u["n"], l["n"]) for u in b["units"] for l in u["lessons"]]
        try:
            i = flat.index((s_["unit"] or 1, s_["lesson"] or 1))
        except ValueError:
            i = 0
        i = max(0, min(i + (1 if cmd == "bk_next" else -1), len(flat) - 1))
        run("UPDATE students SET unit=?, lesson=? WHERE id=?", (flat[i][0], flat[i][1], sid))
        toast(cq_id)
        return show(screen_book, sid)

    if cmd == "bk_go":
        kind = parts[2]
        b_ = book_of(sid)
        if kind == "plan" and b_ and (b_.get("audience") or "").startswith(("дошк", "перв")):
            kind = "plan_kids"
        title = BOOK_KINDS[kind][0]
        edit(chat_id, message_id, "{} — собираю по уроку…".format(title), [])
        body, prompt, cached = ai_book_material(sid, kind)
        if not body:
            t, r = screen_book(sid)
            return edit(chat_id, message_id,
                        "⚠️ Не вышло: {}\n\n".format(esc(AI_LAST["error"][:120] or "нет ИИ")) + t, r)
        head = "{} · {}\n\n".format(title, esc(lesson_label(sid)))
        rows = [[("♻️ Сделать заново", "bk_re:%d:%s" % (sid, kind))]]
        if kind == "voc":
            rows.insert(0, [("📥 В словарь ученика", "bk_voc:%d" % sid)])
        if kind == "hw":
            rows.insert(0, [("📤 Отправить ученику", "bk_hw:%d" % sid)])
        send_ai(chat_id, head + esc(body), prompt, body, "book:" + kind, sid, extra_rows=rows)
        t, r = screen_book(sid)
        return send(chat_id, t, r)

    if cmd == "bk_re":
        kind = parts[2]
        edit(chat_id, message_id, "♻️ Переделываю…", [])
        body, prompt, _ = ai_book_material(sid, kind, force=True)
        if not body:
            return edit(chat_id, message_id, "⚠️ ИИ не ответил.", [[("⬅️ Назад", "book:%d" % sid)]])
        return send_ai(chat_id, "{} · {}\n\n{}".format(BOOK_KINDS[kind][0],
                                                       esc(lesson_label(sid)), esc(body)),
                       prompt, body, "book:" + kind, sid,
                       extra_rows=[[("⬅️ К уроку", "book:%d" % sid)]])

    if cmd == "bk_voc":
        b = book_of(sid)
        s_ = sget(sid)
        body = cache_get(b["id"], lesson_of(b, s_["unit"] or 1, s_["lesson"] or 1)["code"], "voc")
        pairs = []
        for line in (body or "").split("\n"):
            bits = [x.strip() for x in line.split("|")]
            if len(bits) >= 2 and 1 < len(bits[0]) < 60:
                pairs.append((bits[0], bits[1]))
        if not pairs:
            return toast(cq_id, "Не нашла строк вида «единица | перевод»")
        n = add_words(sid, pairs, "педагог")
        toast(cq_id, "Добавлено: {}".format(n))
        if sget(sid)["tg_user_id"]:
            notify_student(sid, "📚 <b>Новые слова от преподавателя</b>\n\n{}".format(
                "\n".join("• {} — {}".format(esc(t), esc(tr)) for t, tr in pairs[:12])),
                [[("🔁 Повторить сейчас", "lrn_go:%d" % sid)]])
        return show(screen_book, sid)

    if cmd == "bk_hw":
        b = book_of(sid)
        s_ = sget(sid)
        body = cache_get(b["id"], lesson_of(b, s_["unit"] or 1, s_["lesson"] or 1)["code"], "hw")
        if not body:
            return toast(cq_id, "Сначала сгенерируйте домашку")
        nxt = next_lesson_date(sid)
        run("INSERT INTO homework (student_id, text, due, created, done) VALUES (?,?,?,?,0)",
            (sid, body[:1500], nxt.isoformat() if nxt else None, today().isoformat()))
        sent = notify_student(sid, "📝 <b>Homework</b>{}\n\n{}".format(
            " for " + fmt_date(nxt) if nxt else "", esc(body[:1500])))
        toast(cq_id, "Отправлено" if sent else "Сохранено")
        return show(screen_book, sid)

    if cmd == "schedm":
        return show(screen_sched_menu, sid)

    if cmd == "studym":
        return show(screen_study_menu, sid)

    if cmd == "warm":
        return show(screen_warm, sid)

    if cmd == "warmgo":
        full = parts[2] == "f"
        edit(chat_id, message_id, "🔥 Собираю материал{}…".format(
            " (это займёт до минуты)" if full else ""), [])
        send_warmup(chat_id, sid, full=full)
        t, r = screen_warm(sid)
        return send(chat_id, t, r)

    if cmd == "warmtopic":
        set_state(chat_id, student_id=sid, pending={"action": "warmtopic", "sid": sid})
        return edit(chat_id, message_id,
                    "🎯 Что отработать? Например: <code>Present Perfect vs Past Simple</code>, "
                    "<code>фразовые глаголы с get</code>, <code>еда и заказ в кафе</code>.",
                    [[("⬅️ Назад", "warm:%d" % sid)]])

    if cmd == "aitest":
        edit(chat_id, message_id, "🔌 Проверяю связь с ИИ…", [])
        return edit(chat_id, message_id, ai_selftest(),
                    [[("🔎 Подобрать адрес", "aiprobe")], [("🔄 Ещё раз", "aitest")],
                     [("⬅️ К ученикам", "menu")]])

    if cmd == "aicont":
        if not ai_last(chat_id):
            return toast(cq_id, "Нечего продолжать")
        toast(cq_id, "Дописываю…")
        send_temp(chat_id, "▶️ Дописываю…")
        out, why = ai_refine(chat_id, "Ты не дописал до конца. Продолжи ровно с того "
                                      "места, где оборвался, не повторяя уже написанное. "
                                      "Пришли только продолжение.")
        if not out:
            return send(chat_id, "⚠️ " + esc(why))
        last = ai_last(chat_id) or {}
        return send_ai(chat_id, esc(out), last.get("prompt", ""), out,
                       last.get("kind", "misc"), last.get("sid"))

    if cmd == "airefine":
        if not ai_last(chat_id):
            return toast(cq_id, "Нечего дополнять")
        set_state(chat_id, pending={"action": "refine"})
        return edit(chat_id, message_id,
                    "✏️ Что поменять или добавить? Например: <code>сделай сложнее</code>, "
                    "<code>добавь пять предложений на Passive</code>, "
                    "<code>убери говорение, оставь только лексику</code>.",
                    [[("🚫 Отмена", "menu")]])

    if cmd == "aiprobe":
        edit(chat_id, message_id, "🔎 Перебираю варианты подключения…", [])
        return edit(chat_id, message_id, ai_probe(),
                    [[("🔄 Проверить", "aitest")], [("⬅️ К ученикам", "menu")]])

    if cmd == "report":
        edit(chat_id, message_id, "📊 Собираю сводку…", [])
        body = text_weekly_report(sid)
        return edit(chat_id, message_id,
                    body or "За последнюю неделю у ученика нет ни повторений, ни упражнений.",
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "quiet":
        run("UPDATE students SET quiet=1-COALESCE(quiet,0) WHERE id=?", (sid,))
        toast(cq_id, "Готово")
        return show(screen_student, sid)

    if cmd == "lvl":
        return edit(chat_id, message_id,
                    "🎚 Уровень ученика — от него зависят задания, которые генерирует ИИ.",
                    [[(l, "lvlset:%d:%s" % (sid, l)) for l in ("A1", "A2", "B1")],
                     [(l, "lvlset:%d:%s" % (sid, l)) for l in ("B2", "C1", "C2")],
                     [("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "lvlset":
        run("UPDATE students SET level=? WHERE id=?", (parts[2], sid))
        flash(chat_id, "✅ Уровень: {}".format(parts[2]))
        return show(screen_student, sid)

    if cmd == "zoom":
        set_state(chat_id, student_id=sid, pending={"action": "zoom", "sid": sid})
        cur = sget(sid)["zoom"]
        return edit(chat_id, message_id,
                    "🎥 Пришлите постоянную ссылку на Zoom для этого ученика.{}\n"
                    "Убрать — «-».".format("\nСейчас: " + esc(cur) if cur else ""),
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "givekey":
        run("UPDATE students SET keys=COALESCE(keys,0)+1 WHERE id=?", (sid,))
        notify_student(sid, "🔑 Вы получили ключик! Его можно потратить на бонусный материал.")
        flash(chat_id, "🔑 Ключик выдан.")
        return show(screen_student, sid)

    if cmd == "del":
        return edit(chat_id, message_id,
                    "🗑 Удалить <b>{}</b> навсегда?\nИсчезнут занятия, оплаты, слова "
                    "и прогресс этого ученика.".format(esc(sget(sid)["name"])),
                    [[("❌ Да, удалить", "delok:%d" % sid)], [("⬅️ Отмена", "st:%d" % sid)]])

    if cmd == "delok":
        name = sget(sid)["name"]
        for table in ("lessons", "payments", "slots", "moves", "appts", "words",
                      "reviews", "homework", "materials", "feedback"):
            run("DELETE FROM {} WHERE student_id=?".format(table), (sid,))
        run("DELETE FROM students WHERE id=?", (sid,))
        flash(chat_id, "🗑 Ученик {} удалён.".format(esc(name)))
        return show(screen_students, chat_id)

    if cmd == "prog":
        return show(screen_progress, sid)

    if cmd == "board":
        t, r = screen_board(chat_id, real_names=True)
        return edit(chat_id, message_id, t, r)

    if cmd == "promo_me":
        send(chat_id, text_share_bot())
        t, r = screen_students(chat_id)
        return edit(chat_id, message_id,
                    "💌 Визитка отправлена ниже — её можно переслать куда угодно.\n\n" + t, r)

    if cmd == "words":
        return show(screen_words, sid)

    if cmd == "waddo":
        set_state(chat_id, student_id=sid, pending={"action": "words", "sid": sid, "by": "педагог"})
        return edit(chat_id, message_id,
                    "➕ Пришлите слова одним сообщением, по одному в строке:\n\n"
                    "<code>apple - яблоко\nto give up - сдаться</code>",
                    [[("⬅️ Назад", "words:%d" % sid)]])

    if cmd == "wpick":
        return show(screen_wpick, sid)

    if cmd == "wdl":
        w = q("SELECT * FROM words WHERE id=?", (int(parts[2]),), one=True)
        if w:
            run("DELETE FROM words WHERE id=?", (w["id"],))
            flash(chat_id, "🗑 Слово удалено: <b>{}</b> — {}.".format(
                esc(w["term"]), esc(w["translation"])))
        return show(screen_wpick, sid)

    if cmd == "share":
        return show(screen_share, sid)

    if cmd in ("sh_st", "sh_pay", "sh_sch", "code", "codek"):
        if cmd == "code":
            text = text_invite(sid, "full")
        elif cmd == "codek":
            text = text_invite(sid, "kid")
        else:
            text = {"sh_st": text_statement, "sh_pay": text_reminder,
                    "sh_sch": text_schedule}[cmd](sid)
        res = send(chat_id, text)
        _t, r = screen_share(sid)
        if res.get("ok"):
            tail = ("\n\n⬇️ Это же сообщение продублировано внизу чата — "
                    "его можно переслать ученику.")
        else:
            tail = ("\n\n⚠️ Отдельным сообщением отправить не вышло ({}). "
                    "Перешлите это сообщение — текст целиком выше.".format(
                        esc(res.get("description", "причина неизвестна"))))
        return edit(chat_id, message_id, text + tail, r)

    if cmd == "more":
        s = sget(sid)
        rows = [[("💵 Ставка за занятие", "rate:%d" % sid)],
                [("🎥 Ссылка на Zoom", "zoom:%d" % sid),
                 ("🎚 {}".format(s["level"] or "уровень"), "lvl:%d" % sid)],
                [("🔑 Выдать ключик", "givekey:%d" % sid),
                 ("🔔 Напоминания: {}".format("выкл" if s["quiet"] else "вкл"),
                  "quiet:%d" % sid)],
                [("🔗 Код: взрослый", "code:%d" % sid),
                 ("🔗 Код: ребёнок", "codek:%d" % sid)],
                [("✏️ Переименовать", "ren:%d" % sid)],
                [("↩️ Убрать последнее занятие", "undo:%d" % sid)],
                [("↩️ Убрать последнюю оплату", "undopay:%d" % sid)],
                [("🗄 В архив", "arch:%d" % sid)],
                [("🗑 Удалить ученика", "del:%d" % sid)],
                [("⬅️ Назад", "st:%d" % sid)]]
        return edit(chat_id, message_id, "⚙️ <b>{}</b>\nСтавка: {}".format(
            esc(s["name"]), rate_text(s) or "не задана"), rows)

    if cmd == "rate":
        rows = [[("{} / {} мин".format(fmt_money(r), d), "rateset:%d:%d:%d" % (sid, r, d))]
                for r, d in RATE_PRESETS]
        rows.append([("✍️ Другая", "ratec:%d" % sid)])
        rows.append([("⬅️ Назад", "st:%d" % sid)])
        return edit(chat_id, message_id, "💵 Ставка для этого ученика:", rows)

    if cmd == "rateset":
        run("UPDATE students SET rate=?, duration=? WHERE id=?",
            (float(parts[2]), int(parts[3]), sid))
        flash(chat_id, "✅ Ставка для <b>{}</b>: {} / {} мин.".format(
            esc(sget(sid)["name"]), fmt_money(float(parts[2])), parts[3]))
        return show(screen_student, sid)

    if cmd == "ratec":
        set_state(chat_id, student_id=sid, pending={"action": "rate", "sid": sid})
        return edit(chat_id, message_id,
                    "Напишите ставку и длительность, например: <code>1800 50</code>\n"
                    "Можно просто сумму — длительность останется прежней.",
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "ren":
        set_state(chat_id, student_id=sid, pending={"action": "rename", "sid": sid})
        return edit(chat_id, message_id, "Новое имя ученика?", [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "arch":
        name = sget(sid)["name"]
        run("UPDATE students SET archived=1 WHERE id=?", (sid,))
        send(chat_id, "🗄 <b>{}</b> в архиве, данные сохранены.".format(esc(name)))
        return show(screen_students, chat_id)

    if cmd == "unarch":
        run("UPDATE students SET archived=0 WHERE id=?", (sid,))
        flash(chat_id, "✅ <b>{}</b> снова в списке.".format(esc(sget(sid)["name"])))
        return show(screen_student, sid)


# -------------------------------------------------------------------- Ввод текстом

def handle_pending(chat_id, pending, text, user_id=None, entities=None):
    action = pending.get("action")
    sid = pending.get("sid")
    if sid is not None and not student(sid):
        set_state(chat_id, pending=None)
        t, r = screen_students(chat_id)
        return send(chat_id, "⚠️ Такого ученика в базе нет — возможно, база очищалась.\n\n" + t, r)

    if action == "exdo":
        items = pending.get("items") or []
        answers = [l.strip() for l in text.strip().split("\n") if l.strip()]
        set_state(chat_id, pending=None)
        send_temp(chat_id, "🔎 Проверяю…")
        res = ai_check(sid, pending.get("kind", ""), items, answers)
        if not res:
            if not sget(sid)["is_self"]:
                run("UPDATE students SET keys=COALESCE(keys,0)+1 WHERE id=?", (sid,))
            return send(chat_id, "⚠️ ИИ не ответил. Попробуйте позже.",
                        [[("⬅️ В меню", "lrn:%d" % sid)]])
        run("INSERT INTO ex_log (on_date, student_id, kind, tasks, answers, feedback) "
            "VALUES (?,?,?,?,?,?)",
            (today().isoformat(), sid, pending.get("kind", ""),
             "\n".join(it["q"] for it in items)[:2000],
             "\n".join(answers)[:2000], res[:2000]))
        return send(chat_id, "📝 <b>Разбор</b>\n\n" + esc(res),
                    [[("🎁 Ещё упражнение", "lrn_ex:%d" % sid)],
                     [("⬅️ В меню", "lrn:%d" % sid)]])

    if action == "refine":
        set_state(chat_id, pending=None)
        send_temp(chat_id, "✏️ Переделываю…")
        out, why = ai_refine(chat_id, text.strip()[:500])
        if not out:
            return send(chat_id, "⚠️ " + esc(why))
        last = ai_last(chat_id) or {}
        return send_ai(chat_id, esc(out), last.get("prompt", ""), out,
                       last.get("kind", "misc"), last.get("sid"))

    if action == "audiofield":
        run("UPDATE audio SET {}=? WHERE id=?".format(pending["field"]),
            (text.strip()[:800], pending["tid"]))
        set_state(chat_id, pending=None)
        t, r = screen_audio_item(pending["tid"])
        return send(chat_id, t, r)

    if action == "audiomove":
        t_ = q("SELECT * FROM audio WHERE id=?", (pending["tid"],), one=True)
        b = BOOKS.get(t_["book"]) if t_ else None
        m = re.search(r"(\d{1,2})[.\s](\d{1,2})", text)
        if not b or not m or not lesson_of(b, int(m.group(1)), int(m.group(2))):
            return send(chat_id, "Не нашла такой урок. Пришлите код вида <code>3.2</code>.")
        run("UPDATE audio SET code=? WHERE id=?",
            ("{}.{}".format(int(m.group(1)), int(m.group(2))), pending["tid"]))
        set_state(chat_id, pending=None)
        t, r = screen_audio_item(pending["tid"])
        return send(chat_id, "✅ Перенесла.\n\n" + t, r)

    if action == "audio_fix":
        b = BOOKS.get(pending["book"])
        r_ = q("SELECT * FROM audio WHERE book=? AND (code IS NULL OR code='') "
               "ORDER BY id LIMIT 1", (pending["book"],), one=True)
        if not b or not r_:
            set_state(chat_id, pending=None)
            t, r = screen_audio_book(pending["book"])
            return send(chat_id, t, r)
        src = ""
        m = re.search(r"\b(wb|pb|sb|tb)\b", text, re.I)
        if m:
            src = m.group(1).upper()
        mc = re.search(r"(\d{1,2})[.\s](\d)", text)
        if not mc or not lesson_of(b, int(mc.group(1)), int(mc.group(2))):
            return send(chat_id, "Не нашла такой урок. Пришлите код вида <code>3.2</code>.")
        code = "{}.{}".format(int(mc.group(1)), int(mc.group(2)))
        run("UPDATE audio SET code=?, kind=COALESCE(NULLIF(?,''),kind) WHERE id=?",
            (code, src, r_["id"]))
        left = q("SELECT COUNT(*) c FROM audio WHERE book=? AND (code IS NULL OR code='')",
                 (pending["book"],), one=True)["c"]
        if left:
            t, r = screen_audio_fix(pending["book"])
            return send(chat_id, "✅ {} → урок {}\n\n".format(esc(r_["name"] or "трек"), code)
                        + t, r)
        set_state(chat_id, pending=None)
        t, r = screen_audio_book(pending["book"])
        return send(chat_id, "✅ Все треки разобраны.\n\n" + t, r)

    if action == "hwdraft":
        b = book_of(sid)
        s_ = sget(sid)
        l = lesson_of(b, s_["unit"] or 1, s_["lesson"] or 1)
        d = draft_get(sid, b["id"], l["code"])
        cur = (d["text"] if d else "") or ""
        new = text.strip() if pending.get("mode") == "set" else (cur + "\n" + text.strip())
        draft_put(sid, b["id"], l["code"], text=new.strip())
        set_state(chat_id, pending=None)
        t, r = screen_hw_draft(sid)
        return send(chat_id, t, r)

    if action in ("bookfield", "lessonfield", "wordlist"):
        b = BOOKS.get(pending["bid"])
        set_state(chat_id, pending=None)
        if not b:
            return send(chat_id, "Учебник не найден.")
        val = text.strip()
        if action == "bookfield":
            b[pending["field"]] = int(re.sub(r"\D", "", val) or 60) \
                if pending["field"] == "lesson_minutes" else val[:120]
            save_book(b)
            flash(chat_id, "✅ Сохранила.")
            t, r = screen_book_admin(b["id"])
            return send(chat_id, t, r)
        if action == "wordlist":
            u = unit_of(b, pending["unit"])
            items = [w.strip() for w in re.split(r"[,\n;]", val) if w.strip()]
            old = list(u.get("wordlist") or []) if pending["mode"] == "bks_wladd" else []
            for w in items:
                if w not in old:
                    old.append(w)
            u["wordlist"] = old[:200]
            save_book(b)
            flash(chat_id, "✅ В юните {} теперь {} слов.".format(u["n"], len(old)))
            t, r = screen_book_units(b["id"], u["n"])
            return send(chat_id, t, r)
        l = lesson_of(b, pending["unit"], pending["lesson"])
        l[pending["field"]] = val[:300]
        save_book(b)
        flash(chat_id, "✅ Сохранила.")
        t, r = screen_book_lessons(b["id"], pending["unit"], pending["lesson"])
        return send(chat_id, t, r)

    if action == "note_text":
        when = parse_when(text)
        set_state(chat_id, pending=None)
        if not when:
            return send(chat_id, "Не поняла, когда напомнить. Добавьте время: "
                                 "«завтра в 10», «через 2 часа», «25.09 18:00».",
                        [[("⏰ Ещё раз", "nt_add")]])
        note_save(chat_id, text.strip(), when)
        flash(chat_id, "✅ Напомню {}.".format(fmt_when(when.isoformat(timespec="minutes"))))
        t, r = screen_notes(chat_id)
        return send(chat_id, t, r)

    if action == "fin_new":
        lines = [l for l in text.splitlines() if l.strip()]
        added = fin_add(lines, force="income" if pending.get("kind") == "i" else "expense")
        set_state(chat_id, pending=None)
        if not added:
            return send(chat_id, "Не разобрала. Нужна сумма и название: "
                                 "<code>пятёрочка 1200</code>")
        body = ["💸 <b>Записала</b>", ""]
        for kind, amount, title, cat in added:
            body.append("{} {} — {} · <i>{}</i>".format(
                "➕" if kind == "income" else "➖", money(amount), esc(title), cat))
        send(chat_id, "\n".join(body))
        t, r = screen_money()
        return send(chat_id, t, r)

    if action == "credit":
        bits = [b.strip() for b in re.split(r"[,;]", text) if b.strip()]
        if len(bits) < 4:
            return send(chat_id, "Нужно минимум четыре части: название, остаток, ставка, "
                                 "платёж.")
        try:
            name = bits[0][:40]
            nums = [float(b.replace(" ", "").replace(",", ".")) for b in bits[1:5]]
        except ValueError:
            return send(chat_id, "Не разобрала числа. Например:\n"
                                 "<code>Тинькофф, 350000, 25.9, 12000</code>")
        fee = nums[3] if len(nums) > 3 else 0
        if pending.get("cid"):
            run("UPDATE credits SET name=?, balance=?, rate=?, min_pay=?, fee=?, "
                "closed=? WHERE id=?",
                (name, nums[0], nums[1], nums[2], fee, 1 if nums[0] <= 0.5 else 0,
                 pending["cid"]))
        else:
            run("INSERT INTO credits (name, balance, rate, min_pay, fee, created) "
                "VALUES (?,?,?,?,?,?)",
                (name, nums[0], nums[1], nums[2], fee, today().isoformat()))
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Кредит «{}» {}.".format(
            esc(name), "обновлён" if pending.get("cid") else "добавлен"))
        t, r = screen_money()
        return send(chat_id, t, r)

    if action == "credit_pay":
        m = re.search(r"[\d][\d ]*(?:[.,]\d+)?", text)
        if not m:
            return send(chat_id, "Нужна сумма платежа, например 12000.")
        amount = float(m.group().replace(" ", "").replace(",", "."))
        c = q("SELECT * FROM credits WHERE id=?", (pending["cid"],), one=True)
        left = max((c["balance"] or 0) - amount, 0)
        run("UPDATE credits SET balance=?, closed=? WHERE id=?",
            (left, 1 if left <= 0.5 else 0, c["id"]))
        run("INSERT INTO fin_tx (on_date, kind, amount, title, category, created) "
            "VALUES (?,?,?,?,?,?)",
            (today().isoformat(), "expense", amount, "Платёж: " + c["name"], "Кредиты",
             datetime.now().isoformat(timespec="seconds")))
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Платёж {} записан. Остаток по «{}»: {}{}".format(
            money(amount), esc(c["name"]), money(left),
            " — закрыт! 🎉" if left <= 0.5 else ""))
        t, r = screen_money()
        return send(chat_id, t, r)

    if action == "warmtopic":
        topic = text.strip()[:120]
        set_state(chat_id, pending=None)
        send_temp(chat_id, "🔥 Собираю материал по теме «{}»…".format(esc(topic)))
        send_warmup(chat_id, sid, full=True, topic=topic)
        t, r = screen_warm(sid)
        return send(chat_id, t, r)

    if action == "petname":
        name = " ".join(text.split())[:24]
        set_state(chat_id, pending=None)
        if not name:
            return send(chat_id, "Имя не распозналось, попробуйте ещё раз.")
        run("UPDATE students SET pet_name=? WHERE id=?", (name, sid))
        t, r = screen_pet(sid)
        return send(chat_id, "✅ Теперь питомца зовут <b>{}</b>.\n\n".format(esc(name)) + t, r)

    if action == "words":
        entries = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            got = parse_words(line)
            entries.append(got[0] if got else (line[:100], ""))
            if len(entries) >= 25:
                break
        if not entries:
            return send(chat_id, "Не разобрала. Пришлите слова по одному в строке — "
                                 "можно парой <code>apple - яблоко</code>, можно одним "
                                 "словом, хоть по-русски.")
        me = sget(sid)
        by = pending.get("by", "педагог")
        set_state(chat_id, pending=None)
        extra, added = "", []

        if AI_KEY:
            send_temp(chat_id, "✨ Оформляю {} {}…".format(
                len(entries), plural(len(entries), ("слово", "слова", "слов"))))
            ids = [run("INSERT INTO words (student_id, term, translation, added_by, due, "
                       "created, raw) VALUES (?,?,?,?,?,?,1)",
                       (sid, t, tr, by, "2099-01-01", today().isoformat()))
                   for t, tr in entries]
            rows_in = q("SELECT * FROM words WHERE id IN ({})".format(
                ",".join("?" * len(ids))), tuple(ids))
            rows_in = sorted(rows_in, key=lambda w: ids.index(w["id"]))
            done, why = ai_format_raw(sid, items=rows_in)
            added = q("SELECT * FROM words WHERE id IN ({}) AND COALESCE(raw,0)=0 "
                      "ORDER BY id".format(",".join("?" * len(ids))), tuple(ids))
            n = len(added)
            if n < len(entries):
                extra = "\n🧺 Без карточки осталось: {}{}".format(
                    len(entries) - n, " — " + why if why else "")
        else:
            pairs = [(t, tr) for t, tr in entries if tr]
            n = add_words(sid, pairs, by)
            for t, tr in entries:
                if not tr:
                    run("INSERT INTO words (student_id, term, translation, added_by, due, "
                        "created, raw) VALUES (?,?,?,?,?,?,1)",
                        (sid, t, "", by, "2099-01-01", today().isoformat()))
            if len(entries) - n:
                extra = "\n🧺 Без перевода: {} — лежат в сырых словах.".format(
                    len(entries) - n)
            added = q("SELECT * FROM words WHERE student_id=? AND COALESCE(raw,0)=0 "
                      "ORDER BY id DESC LIMIT ?", (sid, n))
            added = list(reversed(added))

        head = ("📥 <b>В мой словарь</b> — {} {}{}".format(
                    n, plural(n, ("слово", "слова", "слов")), extra)
                if pending.get("quick") else
                "✅ Добавлено слов: <b>{}</b>{}".format(n, extra))
        body = head
        if added:
            body += "\n\n" + "\n".join(
                "• <b>{}</b>{} — {}".format(
                    esc(w["term"]), " [{}]".format(esc(w["ipa"])) if w["ipa"] else "",
                    esc(w["translation"] or "")) for w in added)
            body += "\n\nПервое повторение — сегодня."
        if pending.get("quick"):
            ids = ",".join(str(w["id"]) for w in added[:25])
            rows = [[("🔁 Повторить сейчас", "lrn_go:%d" % sid)],
                    [("📖 Мой словарь", "myw")]]
            if ids and len(ids) < 60:
                rows.insert(1, [("↩️ Убрать эти слова", "wundo:%s" % ids)])
            send(chat_id, body, rows)
            return
        send(chat_id, body)

        if pending.get("after"):
            if added and me["tg_user_id"]:
                notify_student(sid, "📚 <b>Слова с занятия</b>\n\n{}\n\n"
                                    "Они уже в вашем словаре.".format(
                                        "\n".join("• {} — {}".format(esc(w["term"]),
                                                                     esc(w["translation"]))
                                                  for w in added)),
                               [[("🔁 Повторить сейчас", "lrn_go:%d" % sid)]])
            t, r = screen_after(sid, pending["lid"])
            return send(chat_id, t, r)
        if by == "ученик":
            owner = None if (me["is_guest"] or me["is_self"]) else owner_chat(sid)
            if owner:
                send(owner, "📚 <b>{}</b> добавил(а) {} новых слов в словарь.".format(
                    esc(me["name"]), n))
            t, r = screen_learner(sid)
        elif me["is_self"]:
            t, r = screen_learner(sid)
        else:
            if me["tg_user_id"] and added:
                notify_student(sid, "📚 <b>Новые слова от преподавателя</b>\n\n{}".format(
                    "\n".join("• {} — {}".format(esc(w["term"]), esc(w["translation"]))
                               for w in added)),
                               [[("🔁 Повторить сейчас", "lrn_go:%d" % sid)]])
            t, r = screen_words(sid)
        return send(chat_id, t, r)

    if action == "fbstudent":
        save_feedback(sid, rating=pending.get("rating", 0), text=text.strip(),
                      anon=pending.get("anon", 1))
        set_state(chat_id, pending=None)
        send(chat_id, "🙏 Спасибо, отзыв отправлен!")
        t, r = screen_learner(sid)
        return send(chat_id, t, r)

    if action == "rawadd":
        items = [ln.strip()[:100] for ln in text.splitlines() if ln.strip()][:200]
        if not items:
            return send(chat_id, "Пришлите слова по одному в строке.")
        for it in items:
            run("INSERT INTO words (student_id, term, translation, added_by, due, created, raw) "
                "VALUES (?,?,?,?,?,?,1)",
                (sid, it, "", "педагог", "2099-01-01", today().isoformat()))
        set_state(chat_id, pending=None)
        flash(chat_id, "🧺 В сырые слова добавлено: <b>{}</b>.".format(len(items)))
        t, r = screen_raw(sid)
        return send(chat_id, t, r)

    if action == "rawfix":
        pairs = parse_words(text)
        if not pairs:
            return send(chat_id, "Формат: <code>apple - яблоко</code>, по одному в строке.")
        done = 0
        for term, tr in pairs:
            row = q("SELECT id FROM words WHERE student_id=? AND raw=1 AND "
                    "(LOWER(term)=LOWER(?) OR LOWER(term)=LOWER(?)) LIMIT 1",
                    (sid, term, tr), one=True)
            if row:
                run("UPDATE words SET term=?, translation=?, raw=0, due=? WHERE id=?",
                    (term, tr, today().isoformat(), row["id"]))
            else:
                run("INSERT INTO words (student_id, term, translation, added_by, due, created) "
                    "VALUES (?,?,?,?,?,?)",
                    (sid, term, tr, "педагог", today().isoformat(), today().isoformat()))
            done += 1
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Оформлено слов: <b>{}</b>.".format(done))
        t, r = screen_raw(sid)
        return send(chat_id, t, r)

    if action == "hw":
        due = next_lesson_date(sid)
        run("UPDATE homework SET done=1 WHERE student_id=? AND done=0", (sid,))
        run("INSERT INTO homework (student_id, text, due, created) VALUES (?,?,?,?)",
            (sid, text.strip()[:2000], due.isoformat() if due else None, today().isoformat()))
        set_state(chat_id, pending=None)
        sent = notify_student(sid, "📝 <b>Homework</b>{}\n\n{}".format(
            " for " + fmt_date(due) if due else "", esc(text.strip()[:2000])))
        flash(chat_id, "✅ Домашка сохранена{}.".format(
            " и отправлена ученику" if sent else " (ученик не подключён к боту)"))
        if pending.get("after"):
            t, r = screen_after(sid, pending["lid"])
        else:
            t, r = screen_hw(sid)
        return send(chat_id, t, r)

    if action == "material":
        line = text.strip()
        for_all = line.lower().startswith("всем")
        if for_all:
            line = line[4:].strip(" -—:")
        url = None
        m = re.search(r"(https?://\S+)", line)
        if m:
            url = m.group(1)
            line = line.replace(url, "")
        else:
            # ссылка может быть спрятана под текстом (так вставляет iPhone
            # и пересланные сообщения) — тогда адрес лежит в entities
            for e in (entities or []):
                if e.get("type") == "text_link" and e.get("url"):
                    url = e["url"]
                    break
        if not url:
            return send(chat_id, "Нужна ссылка. Пришлите её обычным текстом, "
                                 "начиная с <code>https://</code> — например:\n"
                                 "<code>Учебник Evolve 5 — https://drive.google.com/…</code>")
        title = line.strip(" -—:\n") or urllib.parse.urlparse(url).netloc or url[:40]
        kind = pending.get("kind", "link")
        run("INSERT INTO materials (student_id, kind, title, ref, created) VALUES (?,?,?,?,?)",
            (0 if for_all else sid, kind, title[:80], url, today().isoformat()))
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Добавлено: <b>{}</b>\n{}".format(esc(title[:80]), esc(url)))
        if kind != "bonus":
            announce_material(sid, title[:80], url, for_all)
        t, r = screen_mat(sid)
        return send(chat_id, t, r)

    if action == "zoom":
        raw = text.strip()
        if raw in ("-", "—"):
            val = None
        else:
            m = re.search(r"(https?://\S+)", raw)
            if m:
                val = m.group(1)[:300]
            else:
                val = next((e["url"] for e in (entities or [])
                            if e.get("type") == "text_link" and e.get("url")), None)
                if not val:
                    return send(chat_id, "Нужна ссылка, начинающаяся с <code>https://</code>. "
                                         "Чтобы убрать ссылку, пришлите <code>-</code>.")
                val = val[:300]
        run("UPDATE students SET zoom=? WHERE id=?", (val, sid))
        set_state(chat_id, pending=None)
        if val:
            flash(chat_id, "✅ Ссылка сохранена:\n{}".format(esc(val)))
            notify_student(sid, "🎥 Ссылка на ваши занятия обновлена — она всегда "
                                "есть в меню бота.", [[("🎥 Подключиться", val)]])
        else:
            flash(chat_id, "✅ Ссылка убрана.")
        t, r = screen_student(sid)
        return send(chat_id, t, r)

    if action == "fbteacher":
        run("INSERT INTO feedback (student_id, side, text, anon, created) VALUES (?,?,?,0,?)",
            (sid, "teacher", text.strip()[:1000], today().isoformat()))
        set_state(chat_id, pending=None)
        sent = notify_student(sid, "💬 <b>Отзыв о занятиях</b>\n\n" + esc(text.strip()[:1000]))
        flash(chat_id, "✅ Отзыв сохранён{}.".format(" и отправлен" if sent else ""))
        t, r = screen_fb(sid)
        return send(chat_id, t, r)

    if action == "cancel_reason":
        record_lesson(chat_id, sid, today(), kind="cancel",
                      charged=pending.get("charged", 1), reason=text.strip()[:100])
        set_state(chat_id, pending=None)
        t, r = screen_student(sid)
        return send(chat_id, t, r)

    if action == "nick":
        if sget(sid)["is_guest"]:
            set_state(chat_id, pending=None)
            return send(chat_id, "Ник гостям выдаёт бот — его можно только перевыбрать кнопкой 🎲")
        nick = re.sub(r"\s+", " ", text.strip())[:20]
        if not nick:
            return send(chat_id, "Ник не может быть пустым.")
        run("UPDATE students SET nick=? WHERE id=?", (nick, sid))
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Ник в рейтинге: <b>{}</b>".format(esc(nick)))
        t, r = screen_learner(sid)
        return send(chat_id, t, r)

    if action == "new_student":
        name = text.strip()[:60]
        new_id = run("INSERT INTO students (chat_id, name) VALUES (?,?)", (chat_id, name))
        set_state(chat_id, student_id=new_id, pending=None)
        flash(chat_id, "✅ Ученик <b>{}</b> добавлен.".format(esc(name)))
        t, r = screen_student(new_id)
        return send(chat_id, t, r)

    if action == "rename":
        old = sget(sid)["name"]
        new = text.strip()[:60]
        run("UPDATE students SET name=? WHERE id=?", (new, sid))
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ {} → <b>{}</b>.".format(esc(old), esc(new)))
        t, r = screen_student(sid)
        return send(chat_id, t, r)

    if action == "rate":
        nums = re.findall(r"\d+", text)
        if not nums:
            return send(chat_id, "Нужно число, например 1800 или «1800 50».")
        rate = float(nums[0])
        dur = int(nums[1]) if len(nums) > 1 else (sget(sid)["duration"] or 60)
        run("UPDATE students SET rate=?, duration=? WHERE id=?", (rate, dur, sid))
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Ставка: {} / {} мин.".format(fmt_money(rate), dur))
        t, r = screen_student(sid)
        return send(chat_id, t, r)

    if action == "note":
        run("UPDATE lessons SET note=? WHERE id=?", (text.strip()[:200], pending["lid"]))
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Тема записана: {}".format(esc(text.strip()[:200])))
        les = q("SELECT * FROM lessons WHERE id=?", (pending["lid"],), one=True)
        if les and les["kind"] == "held":
            t, r = screen_after(sid, pending["lid"])
        else:
            t, r = screen_student(sid)
        return send(chat_id, t, r)

    if action == "custom_lessons":
        m = re.search(r"\d+", text)
        if not m:
            return send(chat_id, "Нужно число занятий, например 6.")
        n = int(m.group())
        s = sget(sid)
        if s["rate"]:
            run("INSERT INTO payments (student_id, lessons, amount, paid_on) VALUES (?,?,?,?)",
                (sid, n, n * s["rate"], today().isoformat()))
            fin_income(n * s["rate"], "Оплата: " + s["name"])
            set_state(chat_id, pending=None)
            flash(chat_id, "✅ Оплата: {} {} · {}. Остаток: <b>{}</b>.".format(
                n, plural(n), fmt_money(n * s["rate"]), stats(sid)["left"]))
            t, r = screen_student(sid)
            return send(chat_id, t, r)
        set_state(chat_id, pending={"action": "amount", "sid": sid, "lessons": n})
        return send(chat_id, "Пакет {} зан. Теперь сумма (или «-»).".format(n))

    if action == "amount":
        n = pending["lessons"]
        raw = text.strip().replace("\u00a0", " ")
        d, amount = today(), 0.0
        if raw not in ("-", "—"):
            dm = re.search(r"\b(\d{1,2}[.\-/]\d{1,2}(?:[.\-/]\d{2,4})?)\b", raw)
            if dm:
                parsed = parse_date(dm.group(1))
                if parsed:
                    d = parsed
                    raw = raw.replace(dm.group(1), " ")
            rm = re.search(r"(https?://\S+)", raw)
            receipt = rm.group(1) if rm else None
            if rm:
                raw = raw.replace(rm.group(1), " ")
            digits = re.sub(r"[^\d.,]", "", raw).replace(",", ".")
            amount = float(digits) if digits.strip(".") else 0.0
        run("INSERT INTO payments (student_id, lessons, amount, paid_on, receipt) "
            "VALUES (?,?,?,?,?)", (sid, n, amount, d.isoformat(), locals().get("receipt")))
        fin_income(amount, "Оплата: " + sget(sid)["name"], d)
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Оплата — <b>{}</b>: {} {} · {} · {}.\nОстаток: <b>{}</b>.".format(
            esc(sget(sid)["name"]), n, plural(n), fmt_money(amount), fmt_date(d),
            stats(sid)["left"]))
        t, r = screen_student(sid)
        return send(chat_id, t, r)

    if action == "lesson_date":
        d = parse_date(text)
        if not d:
            return send(chat_id, "Не поняла дату. Например: 15.09, 15.09.2026, вчера.")
        lid = record_lesson(chat_id, sid, d)
        set_state(chat_id, pending=None)
        t, r = screen_student(sid)
        return send(chat_id, t, [[("✍️ Добавить тему", "note:%d:%d" % (sid, lid))]] + r)

    if action == "move_to":
        d, at = parse_date_time(text)
        if not d:
            return send(chat_id, "Не поняла дату. Например: <code>20.09 17:00</code>")
        run("DELETE FROM moves WHERE student_id=? AND from_date=?", (sid, pending["from"]))
        run("INSERT INTO moves (student_id, from_date, to_date, at) VALUES (?,?,?,?)",
            (sid, pending["from"], d.isoformat(), at or ""))
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Перенос: {} → <b>{} {}</b>.".format(
            fmt_date(pending["from"]), fmt_date(d), at or ""))
        t, r = screen_student(sid)
        return send(chat_id, t, r)

    if action == "dates":
        dates = parse_dates(text)
        if not dates:
            return send(chat_id, "Не разобрала. Формат: <code>22.09 17:00, 25.09 12:00</code>")
        for d, at in dates:
            run("DELETE FROM appts WHERE student_id=? AND on_date=?", (sid, d.isoformat()))
            run("INSERT INTO appts (student_id, on_date, at) VALUES (?,?,?)",
                (sid, d.isoformat(), at))
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Добавлены даты: {}".format(
            ", ".join("{} {}".format(fmt_date(d, True), at).strip() for d, at in dates)))
        t, r = screen_sched(sid)
        return send(chat_id, t, r)

    if action == "schedule":
        run("DELETE FROM slots WHERE student_id=?", (sid,))
        if text.strip() not in ("-", "—"):
            slots = parse_slots(text)
            if not slots:
                return send(chat_id, "Не поняла. Формат: пн 17:00, чт 18:30")
            for wd, at in slots:
                run("INSERT INTO slots (student_id, weekday, at) VALUES (?,?,?)", (sid, wd, at))
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Расписание: {}".format(slots_text(sid) or "очищено"))
        t, r = screen_student(sid)
        return send(chat_id, t, r)

    set_state(chat_id, pending=None)
    return send(chat_id, HELP)


# ----------------------------------------------------------------------- Команды

def find_student(chat_id, name):
    name = name.strip().lower()
    for s in students(chat_id):
        if s["name"].lower().startswith(name):
            return s
    return None


def handle_command(chat_id, user_id, text):
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/").split("@")[0]
    arg = parts[1].strip() if len(parts) > 1 else ""
    st = get_state(chat_id)

    meta_set("owner_chat", chat_id)

    if cmd == "id":
        return send(chat_id, "Ваш Telegram ID: <code>{}</code>".format(user_id))

    if cmd == "db":
        lines = []
        try:
            path = os.path.abspath(DB_PATH)
            size = os.path.getsize(path) if os.path.exists(path) else 0
            lines.append("Файл базы: " + path)
            lines.append("Размер: {} КБ".format(round(size / 1024, 1)))
            lines.append("Папка доступна для записи: " + (
                "да" if os.access(os.path.dirname(path) or ".", os.W_OK) else "НЕТ"))
            for table, label in (("students", "карточек"), ("lessons", "занятий"),
                                 ("payments", "оплат"), ("words", "слов"),
                                 ("reviews", "повторов")):
                n = q("SELECT COUNT(*) c FROM " + table, one=True)["c"]
                lines.append("{}: {}".format(label, n))
            lines.append("Последний запуск: " + str(meta_get("started_at", "—")))
            lines.append("")
            lines.append("Если после перезапуска цифры обнулились — база лежит "
                         "не на постоянном диске, поправьте TG_BOT_DB.")
        except Exception as e:
            lines.append("Ошибка при чтении базы: {}: {}".format(type(e).__name__, e))
        body = "\n".join(lines)
        print("DB INFO:", body.replace("\n", " | "))
        res = tg("sendMessage", chat_id=chat_id, text=body)
        if not res.get("ok"):
            print("DB INFO send failed:", res.get("description"))
        return res

    if cmd in ("start", "help", "menu", "students", "ученики"):
        set_state(chat_id, pending=None)
        t, r = screen_students(chat_id)
        return send(chat_id, (HELP + "\n\n" if cmd in ("start", "help") else "") + t, r)

    if cmd in ("new", "новый"):
        if not arg:
            set_state(chat_id, pending={"action": "new_student"})
            return send(chat_id, "Как зовут ученика?")
        return handle_pending(chat_id, {"action": "new_student"}, arg)

    if cmd == "s":
        s = find_student(chat_id, arg)
        if not s:
            t, r = screen_students(chat_id)
            return send(chat_id, "Не нашла такого ученика.\n\n" + t, r)
        set_state(chat_id, student_id=s["id"], pending=None)
        t, r = screen_student(s["id"])
        return send(chat_id, t, r)

    if cmd in ("month", "месяц"):
        t, r = screen_month(chat_id)
        return send(chat_id, t, r)

    if cmd in ("books", "учебники"):
        if arg.strip() in ("экран", "меню", ""):
            t, r = screen_books()
            return send(chat_id, t, r)
        if not BOOKS:
            return send(chat_id, "Учебники не загружены: положите карты в папку "
                                 "<code>books/</code> рядом с main.py.")
        lines = ["📕 <b>Учебники</b>", ""]
        for b in BOOKS.values():
            lines.append("• <b>{}</b> — {} юнитов, {} уроков, {} мин".format(
                esc(b["title"]), len(b["units"]),
                sum(len(u["lessons"]) for u in b["units"]), b.get("lesson_minutes", 60)))
        who = q("SELECT name, book FROM students WHERE book IS NOT NULL AND archived=0")
        if who:
            lines += ["", "<b>У кого что</b>"]
            for r_ in who:
                lines.append("• {} — {}".format(esc(r_["name"]),
                                                esc(BOOKS.get(r_["book"], {}).get("title", "—"))))
        return send(chat_id, "\n".join(lines))

    if cmd in ("notes", "напоминания", "напомни"):
        if arg.strip():
            when = parse_when(arg)
            if when:
                note_save(chat_id, arg.strip(), when)
                return send(chat_id, "✅ Напомню {}.".format(
                    fmt_when(when.isoformat(timespec="minutes"))),
                    [[("⏰ Все напоминания", "notes")]])
        t, r = screen_notes(chat_id)
        return send(chat_id, t, r)

    if cmd in ("money", "деньги", "траты"):
        t, r = screen_money()
        return send(chat_id, t, r)

    if cmd in ("archive", "архив"):
        t, r = screen_archive(chat_id)
        return send(chat_id, t, r)

    if cmd in ("level", "уровень"):
        me = q("SELECT * FROM students WHERE chat_id=? AND COALESCE(is_self,0)=1",
               (chat_id,), one=True)
        if not me:
            return send(chat_id, "Свой словарь ещё не заведён — откройте «📚 Мой словарь».")
        val = arg.strip().upper()
        if val not in ("A1", "A2", "B1", "B2", "C1", "C2"):
            return send(chat_id, "Ваш уровень: <b>{}</b>\nПоменять: <code>/level C2</code>"
                        .format(level_of(me["id"])))
        run("UPDATE students SET level=? WHERE id=?", (val, me["id"]))
        return send(chat_id, "✅ Ваш уровень для карточек и упражнений: <b>{}</b>".format(val))

    if cmd in ("ai", "ии", "токены"):
        return send(chat_id, text_ai_usage(),
                    [[("🔌 Проверить связь", "aitest")], [("⬅️ К ученикам", "menu")]])

    if cmd in ("aitest", "тест"):
        send_temp(chat_id, "🔌 Проверяю…")
        return send(chat_id, ai_selftest())

    if cmd in ("today", "сегодня", "день"):
        body = text_day(chat_id)
        return send(chat_id, body or "☀️ На сегодня занятий нет.",
                    [[("🗓 Ближайшая неделя", "week")], [("⬅️ К ученикам", "menu")]])

    if cmd in ("week", "неделя"):
        t, r = screen_week(chat_id)
        return send(chat_id, t, r)

    if cmd in ("schedule", "расписание"):
        t, r = screen_schedule_all(chat_id)
        return send(chat_id, t, r)

    if cmd == "export":
        return export_csv(chat_id)

    if cmd in ("backup", "копия"):
        return backup_db(chat_id)

    if cmd == "restore":
        set_state(chat_id, pending={"action": "restore"})
        return send(chat_id, "♻️ Пришлите файл резервной копии (.db) — я заменю им "
                             "текущую базу. Текущая сохранится рядом как .old")

    if cmd in ("mywords", "словарь", "слова"):
        me = self_student(chat_id, user_id)
        t, r = screen_learner(me["id"])
        return send(chat_id, t, r)

    sid = st["student_id"]
    if cmd in ("done", "занятие") and sid:
        d = parse_date(arg) if arg else today()
        if not d:
            return send(chat_id, "Не поняла дату.")
        lid = record_lesson(chat_id, sid, d)
        t, r = screen_student(sid)
        return send(chat_id, t, [[("✍️ Добавить тему", "note:%d:%d" % (sid, lid))]] + r)

    if cmd in ("pay", "оплата") and sid:
        nums = re.findall(r"\d+(?:[.,]\d+)?", arg)
        if not nums:
            t, r = screen_pay(sid)
            return send(chat_id, t, r)
        lessons = int(float(nums[0]))
        rest = arg[arg.find(nums[0]) + len(nums[0]):]
        return handle_pending(chat_id, {"action": "amount", "sid": sid, "lessons": lessons},
                              rest or "-")

    t, r = screen_students(chat_id)
    return send(chat_id, "Не знаю такой команды.\n\n" + HELP + "\n\n" + t, r)


# ------------------------------------------------------------------ Поток ученика

def bind_code(user_id, text):
    """Ищет ученика по коду. Возвращает (ученик, доступ) или (None, None)."""
    code = re.sub(r"[^A-Za-z0-9]", "", text).upper()[:6]
    if not code:
        return None, None
    found = q("SELECT * FROM students WHERE code=? AND code IS NOT NULL "
              "AND COALESCE(is_guest,0)=0", (code,), one=True)
    if found:
        return found, "full"
    found = q("SELECT * FROM students WHERE code_kid=? AND code_kid IS NOT NULL "
              "AND COALESCE(is_guest,0)=0", (code,), one=True)
    if found:
        return found, "kid"
    return None, None


def use_code(found, user_id, access):
    """Код одноразовый: после привязки он гасится."""
    run("UPDATE students SET tg_user_id=?, access=?, code=NULL, code_kid=NULL WHERE id=?",
        (user_id, access, found["id"]))


def learner_flow(chat_id, user_id, text):
    s = student_by_user(user_id)

    # гость ввёл код ученика — переносим его словарь в настоящую карточку
    if s and s["is_guest"] and len(text.strip()) <= 12:
        found, access = bind_code(user_id, text)
        if found:
            run("UPDATE words SET student_id=? WHERE student_id=?", (found["id"], s["id"]))
            run("UPDATE reviews SET student_id=? WHERE student_id=?", (found["id"], s["id"]))
            run("UPDATE students SET nick=COALESCE(nick,?) WHERE id=?", (s["nick"], found["id"]))
            use_code(found, user_id, access)
            run("DELETE FROM students WHERE id=?", (s["id"],))
            send(chat_id, "✅ Готово, вы подключены. Ваши слова сохранились.")
            if found["chat_id"]:
                send(found["chat_id"], "🔗 <b>{}</b> подключился(ась) к боту.".format(
                    esc(found["name"])))
            t, r = screen_learner(found["id"])
            return send(chat_id, t, r)

    if not s:
        found, access = bind_code(user_id, text)
        if not found:
            t, r = screen_welcome()
            hint = ("\n\n<i>Если вы мой ученик — отправьте код, который я вам дала.</i>"
                    if len(text.strip()) <= 12 else "")
            return send(chat_id, t + hint, r)
        if found["tg_user_id"]:
            return send(chat_id, "Этот код уже использован — попросите преподавателя "
                                 "выдать новый.")
        use_code(found, user_id, access)
        send(chat_id, "✅ Готово, вы подключены.")
        if found["chat_id"]:
            send(found["chat_id"], "🔗 <b>{}</b> подключился(ась) к боту.".format(esc(found["name"])))
        s = student(found["id"])

    pending = get_state(chat_id)["pending"]
    if pending:
        return handle_pending(chat_id, pending, text, user_id)
    low = text.strip().lower().lstrip("/")
    if low.startswith(("when", "когда", "расписание")) and (s["access"] or "full") != "kid":
        return send(chat_id, text_when(s["id"]), [[("⬅️ В меню", "lrn:%d" % s["id"])]])
    if low.startswith(("words", "слова", "повтор")):
        ws = due_words(s["id"], 1)
        t, r = screen_card(s["id"], ws[0] if ws else None)
        return send(chat_id, t, r)
    t, r = screen_learner(s["id"])
    return send(chat_id, t, r)


# -------------------------------------------------------------------- Напоминания

def hourly_jobs():
    """Раз в несколько минут: напоминание об оплате через час после занятия."""
    now = datetime.now()
    for s in q("SELECT * FROM students WHERE tg_user_id IS NOT NULL AND archived=0 "
               "AND COALESCE(is_guest,0)=0 AND COALESCE(is_self,0)=0"):
        sid = s["id"]
        st = stats(sid)
        if st["left"] > 0:
            continue
        key = "payrem:%d" % sid
        if meta_get(key) == today().isoformat():
            continue
        occ = [o for o in occurrences(sid, 3, start=today()) if o[0] == today()]
        if not occ:
            continue
        at = occ[0][1] or "00:00"
        try:
            hh, mm = [int(x) for x in at.split(":")]
        except ValueError:
            hh, mm = 0, 0
        start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now < start + timedelta(hours=1):
            continue
        meta_set(key, today().isoformat())
        notify_student(sid, "💳 Это было последнее оплаченное занятие.\n\n"
                            "Реквизиты для оплаты: {}\n"
                            "Напишите преподавателю, какой пакет берём дальше.".format(PAY_DETAILS),
                       [[("💳 Подробнее", "lrn_pay:%d" % sid)]])
        if s["chat_id"]:
            send(s["chat_id"], "🔔 {} отправлено напоминание об оплате "
                               "(занятие было последним оплаченным).".format(esc(s["name"])))


def monthly_feedback():
    for s in q("SELECT * FROM students WHERE tg_user_id IS NOT NULL AND archived=0 "
               "AND COALESCE(is_guest,0)=0 AND COALESCE(is_self,0)=0 AND access='full'"):
        last = meta_get("fb_asked:%d" % s["id"])
        if last and (today() - datetime.strptime(last, "%Y-%m-%d").date()).days < 30:
            continue
        if stats(s["id"])["held"] < 3:
            continue
        ask_feedback(s["id"])


def award_keys():
    """Ключик за полностью повторённый день — не чаще одного раза в неделю."""
    week = "{}-{:02d}".format(*today().isocalendar()[:2])
    for s in q("SELECT * FROM students WHERE tg_user_id IS NOT NULL"):
        sid = s["id"]
        if meta_get("weekkey:%d" % sid) == week:
            continue
        done = q("SELECT COUNT(*) c FROM reviews WHERE student_id=? AND on_date=?",
                 (sid, today().isoformat()), one=True)["c"]
        if done >= KEY_MIN_REVIEWS and due_count(sid) == 0:
            meta_set("weekkey:%d" % sid, week)
            run("UPDATE students SET keys=COALESCE(keys,0)+1 WHERE id=?", (sid,))
            notify_student(sid, "🔑 Все слова на сегодня повторены — держите ключик!\n"
                                "Такой даётся раз в неделю; чаще их приносят серии "
                                "без пропусков и питомец.",
                           [[("🎁 Потратить", "lrn_ex:%d" % sid)]])


def streak_keys():
    """Ключик за серию дней без пропусков."""
    for s in q("SELECT * FROM students WHERE tg_user_id IS NOT NULL AND archived=0"):
        sid = s["id"]
        st = progress(sid)["streak"]
        if st not in (7, 14, 30, 60, 100, 200, 365):
            continue
        key = "streakkey:%d" % sid
        if meta_get(key) == str(st):
            continue
        meta_set(key, str(st))
        run("UPDATE students SET keys=COALESCE(keys,0)+1 WHERE id=?", (sid,))
        notify_student(sid, "🔥 <b>{} {} подряд!</b>\nДержите 🔑 ключик на упражнение.".format(
            st, plural(st, ("день", "дня", "дней"))),
            [[("🎁 Потратить", "lrn_ex:%d" % sid)]])


def hard_words(sid, days=7, limit=5):
    """Слова, которые ученик за период чаще всего забывал."""
    since = (today() - timedelta(days=days)).isoformat()
    return q("SELECT w.term term, w.translation tr, COUNT(*) c FROM reviews r "
             "JOIN words w ON w.id=r.word_id "
             "WHERE r.student_id=? AND r.on_date>=? AND r.grade=0 "
             "GROUP BY r.word_id ORDER BY c DESC, w.term LIMIT ?", (sid, since, limit))


def text_weekly_report(sid):
    """Сводка по ученику за неделю: активность, трудные слова, разбор письменных ответов."""
    s = sget(sid)
    since = (today() - timedelta(days=7)).isoformat()
    revs = q("SELECT COUNT(*) c, COUNT(DISTINCT on_date) d FROM reviews "
             "WHERE student_id=? AND on_date>=?", (sid, since), one=True)
    logs = q("SELECT * FROM ex_log WHERE student_id=? AND on_date>=? ORDER BY id", (sid, since))
    hard = hard_words(sid)
    if not revs["c"] and not logs:
        return None
    lines = ["📊 <b>{}</b> — неделя".format(esc(s["name"])), "",
             "Повторений: <b>{}</b> за {} {}".format(
                 revs["c"], revs["d"], plural(revs["d"], ("день", "дня", "дней"))),
             "Упражнений: <b>{}</b>".format(len(logs))]
    if hard:
        lines += ["", "<b>Хуже всего даются</b>"]
        for h in hard:
            lines.append("• {} — {} ({}×)".format(esc(h["term"]), esc(h["tr"] or ""), h["c"]))
    if logs and ai_allowed()[0]:
        body = "\n\n".join("Задания:\n{}\nОтветы ученика:\n{}\nРазбор:\n{}".format(
            l["tasks"], l["answers"], l["feedback"])[:1800] for l in logs[-3:])
        res = ai_complete(
            "Ниже письменные работы ученика ({}, уровень {}) за неделю.\n\n{}\n\n"
            "Напиши преподавателю по-русски, коротко и по делу:\n"
            "1) две-три ошибки, которые повторяются;\n"
            "2) что уже получается уверенно;\n"
            "3) три конкретные темы или конструкции, которые стоит отработать на занятии.\n"
            "Без markdown-звёздочек, до 120 слов.".format(
                s["name"], s["level"] or "не указан", body),
            max_tokens=450, kind="report", sid=sid)
        if res:
            lines += ["", "<b>Что видно по письменным ответам</b>", esc(res)]
    elif logs:
        lines += ["", "<i>Разбор от ИИ недоступен: закончились токены или нет ключа.</i>"]
    return "\n".join(lines)


def weekly_report():
    """По понедельникам присылает преподавателю сводку по каждому ученику."""
    if today().weekday() != 0 or datetime.now().hour < (DIGEST_HOUR or 9):
        return
    wk = today().isoformat()
    if meta_get("reportweek") == wk:
        return
    meta_set("reportweek", wk)
    for s in q("SELECT * FROM students WHERE archived=0 AND COALESCE(is_guest,0)=0 "
               "AND COALESCE(is_self,0)=0 AND chat_id IS NOT NULL"):
        body = text_weekly_report(s["id"])
        if body:
            send(s["chat_id"], body, [[("👤 Карточка", "st:%d" % s["id"])]])


def weekly_board():
    """По понедельникам — ключик тому, кто больше всех повторял за неделю."""
    if today().weekday() != 0:
        return
    wk = today().isoformat()
    if meta_get("boardweek") == wk:
        return
    since = (today() - timedelta(days=7)).isoformat()
    rows = q("SELECT s.id id, s.name name, COUNT(r.id) c FROM students s "
             "JOIN reviews r ON r.student_id=s.id AND r.on_date>=? "
             "WHERE s.tg_user_id IS NOT NULL AND s.archived=0 "
             "GROUP BY s.id ORDER BY c DESC LIMIT 1", (since,))
    meta_set("boardweek", wk)
    if not rows or not rows[0]["c"]:
        return
    win = rows[0]
    run("UPDATE students SET keys=COALESCE(keys,0)+1 WHERE id=?", (win["id"],))
    notify_student(win["id"], "🏆 <b>Вы лучший на прошлой неделе!</b>\n"
                              "{} {} — и 🔑 ключик в награду.".format(
                                  win["c"], plural(win["c"], ("повторение", "повторения",
                                                              "повторений"))),
                   [[("🎁 Потратить", "lrn_ex:%d" % int(win["id"]))]])


def daily_digest():
    if not DIGEST_HOUR:
        return
    now = datetime.now()
    if now.hour < DIGEST_HOUR or meta_get("digest_date") == today().isoformat():
        return
    meta_set("digest_date", today().isoformat())

    for row in q("SELECT DISTINCT chat_id FROM students"):
        chat_id = row["chat_id"]
        body = text_day(chat_id)
        if body:
            send(chat_id, body)

    for s in q("SELECT * FROM students WHERE tg_user_id IS NOT NULL AND archived=0"):
        n = due_count(s["id"])
        if n:
            send(s["tg_user_id"], "📚 Пора повторить слова: сегодня <b>{}</b>.".format(n),
                 [[("🔁 Начать", "lrn_go:%d" % s["id"])]])


# ---------------------------------------------------------------- Резервные копии

TABLES = (("students", "карточек"), ("lessons", "занятий"), ("payments", "оплат"),
          ("words", "слов"), ("reviews", "повторов"))


def db_snapshot():
    """Целостный снимок базы (безопасен, даже если бот в этот момент пишет)."""
    tmp = DB_PATH + ".snapshot"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(tmp)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    with open(tmp, "rb") as f:
        data = f.read()
    os.remove(tmp)
    return data


def db_summary(path=None):
    """Строка вида «учеников 7 · занятий 142 · слов 310» для подписи к копии."""
    conn = sqlite3.connect(path or DB_PATH)
    parts = []
    try:
        for table, label in TABLES:
            try:
                parts.append("{} {}".format(
                    label, conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]))
            except sqlite3.Error:
                pass
    finally:
        conn.close()
    return " · ".join(parts)


def backup_db(chat_id, caption=None):
    try:
        data = db_snapshot()
    except Exception as e:
        return send(chat_id, "⚠️ Не вышло сделать копию: <code>{}: {}</code>".format(
            type(e).__name__, esc(str(e))))
    name = "tutor_{}.db".format(datetime.now().strftime("%Y-%m-%d_%H%M"))
    text = caption or "🗂 Копия базы"
    res = send_bytes(chat_id, name, data,
                     "{}\n{}\n{} КБ".format(text, db_summary(), round(len(data) / 1024, 1)))
    if not res.get("ok"):
        send(chat_id, "⚠️ Копия собралась, но Telegram не принял файл: {}".format(
            esc(str(res.get("description"))[:200])))
    return res


def auto_backup():
    """Раз в сутки присылает владельцу файл базы."""
    if not BACKUP_HOUR:
        return
    if datetime.now().hour < BACKUP_HOUR or meta_get("backup_date") == today().isoformat():
        return
    target = OWNER_ID or owner_home()
    if not target:
        return
    meta_set("backup_date", today().isoformat())
    backup_db(target, "🗂 Ежедневная копия базы за " + today().strftime("%d.%m.%Y") +
                      "\nСохраните файл: им можно восстановить бота командой /restore.")


def restore_db(chat_id, data, filename=""):
    """Заменяет базу присланным файлом, предварительно проверив его."""
    incoming = DB_PATH + ".incoming"
    with open(incoming, "wb") as f:
        f.write(data)
    try:
        conn = sqlite3.connect(incoming)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("файл повреждён")
            have = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            missing = [t for t, _ in TABLES if t not in have]
            if missing:
                raise sqlite3.DatabaseError("нет таблиц: " + ", ".join(missing))
        finally:
            conn.close()
    except Exception as e:
        os.remove(incoming)
        return send(chat_id, "⚠️ Это не похоже на базу бота: <code>{}</code>\n"
                             "Восстановление отменено, текущая база не тронута.".format(
                                 esc(str(e))))
    summary = db_summary(incoming)
    if os.path.exists(DB_PATH):
        try:
            os.replace(DB_PATH, DB_PATH + ".old")
        except OSError:
            pass
    os.replace(incoming, DB_PATH)
    db().close()
    return send(chat_id, "♻️ База восстановлена из файла <b>{}</b>.\n{}\n\n"
                         "Прежняя сохранена рядом как <code>{}</code>.".format(
                             esc(filename or "копия"), esc(summary),
                             esc(os.path.basename(DB_PATH) + ".old")))


def handle_document(chat_id, doc):
    """Владелец прислал файл: принимаем .db только сразу после команды /restore."""
    name = doc.get("file_name") or "файл"
    pending = get_state(chat_id)["pending"] or {}

    if name.lower().endswith(".json") and pending.get("action") != "audio":
        try:
            data = download_file(doc.get("file_id"))
            b = json.loads(data.decode("utf-8"))
        except Exception as e:
            return send(chat_id, "⚠️ Не разобрала файл: <code>{}</code>".format(esc(str(e)[:120])))
        if not (isinstance(b, dict) and b.get("id") and b.get("units")):
            return send(chat_id, "Это не похоже на карту учебника: нужны поля id и units.")
        save_book(b)
        u, l, w = book_stats(b)
        return send(chat_id, "📕 <b>{}</b> загружен: {} юнитов, {} уроков, {} слов.".format(
            esc(b["title"]), u, l, w), [[("Открыть", "bks_open:%s" % b["id"])]])

    if pending.get("action") == "audio_book":
        b = BOOKS.get(pending["book"])
        if not b:
            set_state(chat_id, pending=None)
            return send(chat_id, "Учебник не найден.")
        code, track, source = audio_match(b, name)
        fresh = audio_store(b, name, doc.get("file_id"), code, source, track,
                            doc.get("file_unique_id", ""))
        if not fresh:
            return send(chat_id, "↩️ {} уже был загружен — пропускаю.".format(esc(name[:50])),
                        [[("✅ Готово", "bka_book:%s" % b["id"])]])
        done = q("SELECT COUNT(*) c FROM audio WHERE book=? AND code<>''", (b["id"],),
                 one=True)["c"]
        left = q("SELECT COUNT(*) c FROM audio WHERE book=? AND (code IS NULL OR code='')",
                 (b["id"],), one=True)["c"]
        return send(chat_id, "🎧 {} → {}{}\n<i>разложено {}, не разобрано {}</i>".format(
            esc(name[:50]), "урок " + code if code else "не разобрала",
            " · " + source if source else "", done, left),
            [[("✅ Готово", "bka_book:%s" % b["id"])]])

    if pending.get("action") == "audio":
        b = pending.get("book")
        code = pending.get("code")
        run("INSERT INTO audio (book, code, track, file_id, kind, name, created) "
            "VALUES (?,?,?,?,?,?,?)",
            (b, code, pending.get("track", ""), doc.get("file_id"), "audio",
             name[:80], today().isoformat()))
        n = q("SELECT COUNT(*) c FROM audio WHERE book=? AND code=?", (b, code),
              one=True)["c"]
        return send(chat_id, "🎧 <b>{}</b> — привязан к уроку {} (всего {}).\n"
                             "Можно прислать ещё, я жду.".format(esc(name[:60]), code, n),
                    [[("✅ Хватит", "bka:%s:%d:%d" % (b, pending.get("unit", 1),
                                                     pending.get("lesson", 1)))]])

    if pending.get("action") == "matfile":
        sid = pending.get("sid")
        set_state(chat_id, pending=None)
        if not sget(sid)["id"]:
            return send(chat_id, "⚠️ Ученик не найден — материал не сохранён.")
        run("INSERT INTO materials (student_id, kind, title, ref, created) VALUES (?,?,?,?,?)",
            (sid, "file", name[:80], doc.get("file_id"), today().isoformat()))
        flash(chat_id, "✅ Файл сохранён: <b>{}</b>".format(esc(name[:80])))
        notify_student(sid, "📎 <b>Новый материал</b>\n{}".format(esc(name[:80])))
        t, r = screen_mat(sid)
        return send(chat_id, t, r)

    if pending.get("action") != "restore":
        return send(chat_id, "Получила файл <b>{}</b>, но ничего с ним не делаю.\n\n"
                             "Чтобы сохранить его как материал ученика — откройте карточку "
                             "ученика → 📎 Материалы → «Загрузить файл», и пришлите файл "
                             "следом.\nЧтобы восстановить базу из копии — отправьте "
                             "/restore, а потом файл.".format(esc(name)))
    set_state(chat_id, pending=None)
    if not name.lower().endswith(".db"):
        return send(chat_id, "Нужен файл базы с расширением .db — этот не подходит.")
    if (doc.get("file_size") or 0) > 45 * 1024 * 1024:
        return send(chat_id, "Файл слишком большой для Telegram Bot API (лимит ~50 МБ).")
    try:
        data = download_file(doc.get("file_id"))
    except Exception as e:
        return send(chat_id, "⚠️ Не вышло скачать файл: <code>{}: {}</code>".format(
            type(e).__name__, esc(str(e))))
    if not data:
        return send(chat_id, "⚠️ Telegram не отдал файл. Попробуйте прислать ещё раз.")
    return restore_db(chat_id, data, name)


# --------------------------------------------------------------------- Диспетчер

def is_owner(user_id):
    return OWNER_ID == 0 or user_id == OWNER_ID


def handle(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg.get("from", {}).get("id")
        if msg.get("audio") or msg.get("voice"):
            if not is_owner(user_id):
                return
            a = msg.get("audio") or msg.get("voice")
            a = dict(a)
            a.setdefault("file_name", a.get("title") or "аудио")
            return handle_document(chat_id, a)
        if msg.get("document") or msg.get("photo"):
            if not is_owner(user_id):
                return
            cap = msg.get("caption") or ""
            when = parse_when(cap) if cap else None
            if when:
                if msg.get("document"):
                    doc = msg["document"]
                    note_save(chat_id, cap, when, doc.get("file_id"), "doc",
                              doc.get("file_name"))
                else:
                    note_save(chat_id, cap, when, msg["photo"][-1].get("file_id"), "photo",
                              "фото")
                return send(chat_id, "✅ Напомню {} и пришлю файл.".format(
                    fmt_when(when.isoformat(timespec="minutes"))),
                    [[("⏰ Все напоминания", "notes")]])
            if msg.get("photo"):
                return send(chat_id, "Чтобы я напомнила с этим фото, добавьте подпись "
                                     "со временем: «завтра в 10».")
            return handle_document(chat_id, msg["document"])
        text = msg.get("text") or ""
        if not text.strip():
            return
        if not is_owner(user_id):
            if text.startswith("/id"):
                return send(chat_id, "Ваш Telegram ID: <code>{}</code>".format(user_id))
            return learner_flow(chat_id, user_id, text)
        if text.startswith("/"):
            return handle_command(chat_id, user_id, text)
        pending = get_state(chat_id)["pending"]
        if pending:
            return handle_pending(chat_id, pending, text, user_id, msg.get("entities"))
        if is_owner(user_id) and re.match(r"^\s*(напомни|напомнить|заметка)\b", text,
                                          re.I):
            body = re.sub(r"^\s*(напомни(ть)?|заметка)[\s,:-]*", "", text, flags=re.I)
            when = parse_when(body)
            if when:
                note_save(chat_id, body.strip(), when)
                return send(chat_id, "✅ Напомню {}: {}".format(
                    fmt_when(when.isoformat(timespec="minutes")), esc(body.strip()[:100])),
                    [[("⏰ Все напоминания", "notes")]])
            return send(chat_id, "Не поняла, когда напомнить. Например: "
                                 "<code>напомни завтра в 10 позвонить в клинику</code>")
        if is_owner(user_id) and looks_like_money(text):
            added = fin_add([l for l in text.splitlines() if l.strip()])
            if added:
                body = ["💸 <b>Записала</b>", ""]
                for kind, amount, title, cat in added:
                    body.append("{} {} — {} · <i>{}</i>".format(
                        "➕" if kind == "income" else "➖", money(amount), esc(title), cat))
                inc, exp, _ = fin_month()
                body += ["", "С начала месяца: +{} / −{}".format(money(inc), money(exp))]
                return send(chat_id, "\n".join(body),
                            [[("💰 Деньги", "money")]])
        if is_owner(user_id) and looks_like_wordlist(text):
            me = self_student(chat_id, user_id)
            return handle_pending(chat_id,
                                  {"action": "words", "sid": me["id"], "by": "педагог",
                                   "quick": 1},
                                  text, user_id, msg.get("entities"))
        t, r = screen_students(chat_id)
        return send(chat_id, t, r)

    if "callback_query" in update:
        cq = update["callback_query"]
        user_id = cq["from"]["id"]
        msg = cq.get("message") or {}
        chat_id = msg.get("chat", {}).get("id")
        if not chat_id:
            return
        return handle_callback(chat_id, msg["message_id"], cq["id"], cq.get("data") or "", user_id)


def report_error(update=None):
    """Присылает владельцу короткий отчёт об ошибке, чтобы не искать в логах."""
    if not OWNER_ID:
        return
    tb = traceback.format_exc().strip().splitlines()
    where = [l.strip() for l in tb if l.strip().startswith("File \"")][-1:] or ["—"]
    what = tb[-1] if tb else "—"
    hint = ""
    if isinstance(update, dict):
        cq = update.get("callback_query") or {}
        if cq:
            hint = "\nКнопка: <code>{}</code>".format(esc(cq.get("data", "")))
        else:
            txt = ((update.get("message") or {}).get("text") or "")[:60]
            if txt:
                hint = "\nСообщение: <code>{}</code>".format(esc(txt))
    tg("sendMessage", chat_id=OWNER_ID, parse_mode="HTML",
       text="⚠️ <b>Ошибка в боте</b>\n<code>{}</code>\n<code>{}</code>{}".format(
           esc(what[:250]), esc(where[0][:250]), hint))


def main():
    if not TOKEN:
        raise SystemExit("Задайте токен: export TG_BOT_TOKEN='...'")
    db().close()
    me = tg("getMe").get("result", {})
    if me.get("username"):
        meta_set("username", me["username"])
    meta_set("started_at", datetime.now().strftime("%d.%m.%Y %H:%M"))
    print("Бот запущен: @" + str(me.get("username")))
    load_books()
    print("Учебники:", ", ".join("{} ({} юнитов)".format(b["title"], len(b["units"]))
                                 for b in BOOKS.values()) or "не найдены")
    n_students = q("SELECT COUNT(*) c FROM students", one=True)["c"]
    print("База данных:", os.path.abspath(DB_PATH), "| учеников:", n_students)
    if OWNER_ID and n_students == 0:
        send(OWNER_ID, "⚠️ <b>База пустая.</b>\nФайл: <code>{}</code>\n\n"
                       "Если это после обновления бота — данные не сохранились. "
                       "Пропишите <code>TG_BOT_DB=/app/data/tutor.db</code> в переменных "
                       "окружения, затем отправьте /restore и пришлите последнюю копию.".format(
                           esc(os.path.abspath(DB_PATH))))
    tg("setMyCommands", commands=[
        {"command": "students", "description": "Ученики"},
        {"command": "today", "description": "Занятия сегодня"},
        {"command": "money", "description": "Деньги и кредиты"},
        {"command": "notes", "description": "Напоминания"},
        {"command": "books", "description": "Учебники"},
        {"command": "ai", "description": "Расход токенов ИИ"},
        {"command": "level", "description": "Мой уровень для ИИ-заданий"},
        {"command": "week", "description": "Ближайшая неделя"},
        {"command": "schedule", "description": "Моё расписание"},
        {"command": "month", "description": "Итоги месяца"},
        {"command": "export", "description": "Выгрузка CSV"},
        {"command": "mywords", "description": "Мой словарь"},
        {"command": "backup", "description": "Резервная копия базы"},
        {"command": "restore", "description": "Восстановить из копии"},
        {"command": "db", "description": "Где лежит база"},
        {"command": "help", "description": "Справка"},
    ])
    offset = None
    while True:
        res = tg("getUpdates", offset=offset, timeout=30,
                 allowed_updates=["message", "callback_query"])
        for u in res.get("result", []):
            offset = u["update_id"] + 1
            try:
                handle(u)
            except Exception:
                traceback.print_exc()
                report_error(u)
        for job in (daily_digest, hourly_jobs, monthly_feedback, award_keys,
                    pet_jobs, streak_keys, weekly_board, weekly_report, fin_ask,
                    notes_job, auto_backup):
            try:
                job()
            except Exception:
                traceback.print_exc()
        if not res.get("result"):
            time.sleep(1)


if __name__ == "__main__":
    main()
