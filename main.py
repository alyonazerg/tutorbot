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
from datetime import date, datetime, timedelta

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
PET_REMIND_HOUR = int(os.environ.get("TG_PET_HOUR", "18") or 0)  # 0 — без напоминаний
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
    "/week — расписание на неделю\n"
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


def send(chat_id, text, rows=None):
    """Отправка с подстраховкой: если Telegram не принял разметку — шлём простым текстом."""
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
    rows.append([("🗓 Неделя", "week"), ("📅 Расписание", "sched_all")])
    rows.append([("📚 Мой словарь", "myw"), ("🏆 Рейтинг", "board")])
    rows.append([("💌 Визитка", "promo_me")])
    rows.append([("🗄 Архив", "arch_list"), ("📁 CSV", "export")])
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

    rows = [
        [("✅ Провела", "done:%d" % sid), ("📅 Другой датой", "doned:%d" % sid)],
        [("💰 Оплата", "pay:%d" % sid), ("🚫 Отмена урока", "cancel:%d" % sid)],
        [("🔁 Перенести", "move:%d" % sid), ("🗓 Расписание", "sched:%d" % sid)],
        [("📝 Домашка", "hw:%d" % sid), ("📎 Материалы", "mat:%d" % sid)],
        [("📚 Слова", "words:%d" % sid), ("🔥 Warm-up", "warm:%d" % sid)],
        [("📈 Прогресс", "prog:%d" % sid), ("💬 Отзывы", "fb:%d" % sid)],
        [("📋 История", "hist:%d" % sid)],
        [("📤 Ученику", "share:%d" % sid), ("⚙️ Ещё", "more:%d" % sid)],
        [("⬅️ К ученикам", "menu")],
    ]
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


def ai_complete(prompt, max_tokens=900, kind="misc", sid=None):
    """Запрос к ИИ. Возвращает текст или None, если ключа нет или сервис недоступен."""
    ok, _ = ai_allowed()
    if not ok:
        return None
    if AI_FORMAT == "anthropic":
        payload = {"model": AI_MODEL, "max_tokens": max_tokens,
                   "messages": [{"role": "user", "content": prompt}]}
        headers = {"x-api-key": AI_KEY, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
    else:
        payload = {"model": AI_MODEL, "max_tokens": max_tokens,
                   "messages": [{"role": "user", "content": prompt}]}
        headers = {"Authorization": "Bearer " + AI_KEY,
                   "Content-Type": "application/json"}
    req = urllib.request.Request(AI_URL, data=json.dumps(payload).encode("utf-8"),
                                 method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode("utf-8"))
        u = data.get("usage") or {}
        ai_log(kind, sid,
               u.get("input_tokens", u.get("prompt_tokens", 0)),
               u.get("output_tokens", u.get("completion_tokens", 0)))
        if AI_FORMAT == "anthropic":
            return "".join(b.get("text", "") for b in data.get("content", [])).strip()
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        print("AI HTTP", e.code, e.read().decode("utf-8", "replace")[:300])
    except Exception as e:
        print("AI error:", type(e).__name__, e)
    return None


def ai_warmup(sid):
    ws = last_batch(sid, 10) or q(
        "SELECT * FROM words WHERE student_id=? AND COALESCE(raw,0)=0 ORDER BY id DESC LIMIT 10",
        (sid,))
    if not ws:
        return None
    pairs = "; ".join("{} — {}".format(w["term"], w["translation"]) for w in ws)
    prompt = (
        "Ты помогаешь преподавателю английского готовить разминку к уроку.\n"
        "Лексика ученика: {}\n\n"
        "Сделай по-английски, уровень A2:\n"
        "1) шесть предложений gap-fill (пропуск обозначай ______), каждое с одним из слов, "
        "предложения бытовые и понятные;\n"
        "2) ключи к ним одной строкой;\n"
        "3) четыре вопроса для обсуждения, в ответах на которые естественно использовать "
        "эту лексику.\n\n"
        "Оформи простым текстом с заголовками, без markdown-звёздочек, коротко."
    ).format(pairs)
    return ai_complete(prompt, kind="warmup", sid=sid)


def ai_format_raw(sid, limit=15):
    """Оформляет сырые слова: транскрипция, определение, синонимы, пример, перевод."""
    items = raw_words(sid)[:limit]
    if not items:
        return 0, "Сырых слов нет."
    ok, why = ai_allowed()
    if not ok:
        return 0, why
    terms = "; ".join(w["term"] for w in items)
    prompt = (
        "Ты составляешь словарные карточки для преподавателя английского (уровень C1).\n"
        "Слова: {}\n\n"
        "Для каждого слова верни объект с полями:\n"
        'term — слово по-английски (если дано по-русски, подбери английский эквивалент);\n'
        'ipa — транскрипция в квадратных скобках не нужна, только символы;\n'
        'definition — определение по-английски, как в толковом словаре, до 15 слов;\n'
        'syn — 2-3 синонима через запятую;\n'
        'ant — 1-2 антонима через запятую (пустая строка, если их нет);\n'
        'coll — одно типичное сочетание с этим словом;\n'
        'example — предложение с этим словом, естественное и не учебное;\n'
        'translation — перевод на русский, 1-3 слова.\n\n'
        "Верни массив объектов в том же порядке."
    ).format(terms)
    data = ai_json(prompt, max_tokens=260 * len(items) + 400, kind="cards", sid=sid)
    if not isinstance(data, list):
        return 0, "ИИ не ответил или вернул непонятный формат. Попробуйте ещё раз."
    by_term = {(w["term"] or "").strip().lower(): w for w in items}
    done = 0
    for i, obj in enumerate(data):
        if not isinstance(obj, dict):
            continue
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
    return done, ""


def ai_json(prompt, max_tokens=1200, kind="misc", sid=None):
    """Просит ИИ вернуть JSON и разбирает его. None, если не вышло."""
    raw = ai_complete(prompt + "\n\nОтветь ТОЛЬКО валидным JSON, без пояснений "
                               "и без ```.", max_tokens, kind, sid)
    if not raw:
        return None
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
    lines += ["", "<i>Модель: {}</i>".format(esc(AI_MODEL))]
    return "\n".join(lines)


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
        lines += ["", "📝 <b>Домашнее задание</b>", esc(hw["text"])]
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


# ---------------------------------------------------------------- Упражнения ИИ

EX_TYPES = [
    ("translate", "✍️ Перевод фраз", "5 фраз с русского на английский",
     "Составь 5 коротких бытовых фраз по-русски для перевода на английский. В каждой "
     "естественно используется одно из слов ученика. q — фраза по-русски, a — эталонный "
     "перевод."),
    ("context", "🧩 Слово в контексте", "выбрать верное употребление",
     "Составь 5 заданий: слово ученика и три варианта предложения (A, B, C), где слово "
     "употреблено верно только в одном. q — слово и три варианта с новой строки, "
     "a — верная буква и почему остальные не подходят."),
    ("error", "🔍 Найди ошибку", "исправить 5 предложений",
     "Составь 5 предложений со словами ученика, в каждом одна типичная ошибка русскоязычного "
     "студента (артикль, предлог, время, порядок слов). q — предложение с ошибкой, "
     "a — исправленный вариант и в чём была ошибка."),
    ("colloc", "🔗 Сочетаемость", "подобрать пары и предлоги",
     "Составь 5 заданий на сочетаемость слов ученика: пропущен предлог или часть устойчивого "
     "сочетания, пропуск обозначь ______. q — предложение с пропуском, a — что вставить."),
    ("dialog", "🎭 Мини-диалог", "ответить репликами в ситуации",
     "Придумай бытовую ситуацию и 5 реплик собеседника, на которые ученик отвечает, "
     "используя свои слова. q — реплика собеседника и подсказка, какое слово применить, "
     "a — пример подходящего ответа."),
]


def ex_words(sid, n=12):
    ws = q("SELECT * FROM words WHERE student_id=? AND COALESCE(raw,0)=0 "
           "ORDER BY COALESCE(seen,''), id DESC LIMIT ?", (sid, n))
    return ws


def ai_exercise(sid, kind):
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
    prompt = (
        "Ты помогаешь ученику практиковать английский по его собственной лексике.\n"
        "Уровень ученика: {}.\nСлова ученика: {}\n\n{}\n\n"
        "Верни объект с полями: title (короткое название по-русски), "
        "intro (одна строка-инструкция по-русски), items (массив из 5 объектов q и a)."
    ).format(s["level"] or "A2-B1", pairs, spec[3])
    data = ai_json(prompt, max_tokens=1100, kind="ex:" + kind, sid=sid)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None, "ИИ не ответил. Ключик не потрачен, попробуйте ещё раз."
    items = [{"q": str(i.get("q", ""))[:400], "a": str(i.get("a", ""))[:400]}
             for i in data["items"][:6] if isinstance(i, dict) and i.get("q")]
    if not items:
        return None, "ИИ вернул пустое задание. Ключик не потрачен."
    return {"title": str(data.get("title") or spec[1])[:80],
            "intro": str(data.get("intro") or "")[:200], "items": items}, ""


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


def screen_ex(sid):
    s = sget(sid)
    keys = s["keys"] or 0
    lines = ["🎁 <b>Упражнения</b>", "",
             "Бот составит задание по вашим словам и проверит ответы.",
             "Одно упражнение — один 🔑 ключик.", "",
             "Ключиков у вас: <b>{}</b>".format(keys)]
    if not keys:
        lines += ["", "<i>Ключики дают за: все повторения за день, новую стадию питомца, "
                      "серию без пропусков и победу в рейтинге. Ещё их выдаёт "
                      "преподаватель.</i>"]
    rows = [[("{} — {}".format(title, hint), "lrn_exgo:%d:%s" % (sid, k))]
            for k, title, hint, _ in EX_TYPES] if keys else []
    rows.append([("⬅️ Назад", "lrn:%d" % sid)])
    return "\n".join(lines), rows


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
            [("✏️ {} питомца".format("Переименовать" if p["named"] else "Дать имя"),
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
        if not PET_REMIND_HOUR or now.hour < PET_REMIND_HOUR or now.hour >= 22:
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
        rows = [[("🔁 Повторить ({})".format(due), "lrn_go:%d" % sid)],
                [("➕ Добавить слова", "lrn_add:%d" % sid),
                 ("📖 Мои слова", "lw:%d" % sid)],
                [("🧺 Сырые слова ({})".format(len(raw_words(sid))), "rawlist:%d" % sid)],
                [("🎁 Упражнения ({}🔑)".format(s["keys"] or 0), "lrn_ex:%d" % sid)],
                [("📈 Прогресс", "lrn_prog:%d" % sid), ("🏆 Рейтинг", "lrn_board:%d" % sid)],
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


def screen_words_menu(sid):
    due, total = due_count(sid), word_count(sid)
    p = progress(sid)
    return ("📚 <b>Словарь</b>\n\nСлов: <b>{}</b> · выучено: <b>{}</b> ({}%)\n"
            "На сегодня: <b>{}</b> · дней подряд: <b>{}</b>".format(
                total, p["learned"], p["pct"], due, p["streak"]),
            [[("🔁 Повторить ({})".format(due), "lrn_go:%d" % sid)],
             [("➕ Добавить слова", "lrn_add:%d" % sid), ("📖 Мои слова", "lw:%d" % sid)],
             [("📈 Прогресс", "lrn_prog:%d" % sid), ("🏆 Рейтинг", "lrn_board:%d" % sid)],
             [("⬅️ Назад", "lrn:%d" % sid)]])


def screen_more_menu(sid):
    s = sget(sid)
    rows = [[("💳 Оплата", "lrn_pay:%d" % sid), ("🗓 Все даты", "lrn_when:%d" % sid)],
            [("💬 Отзыв преподавателю", "lrn_fb:%d" % sid)]]
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
        lines.append(esc(w["definition"]))
    for tag, val in (("Syn", w["syn"]), ("Ant", w["ant"]), ("Coll", w["coll"])):
        if val:
            lines.append("<i>{}:</i> {}".format(tag, esc(val)))
    if w["example"]:
        ex = re.sub(r"(?i)\b({})\b".format(re.escape(w["term"])),
                    lambda m: "<b>{}</b>".format(m.group(0)), esc(w["example"]))
        lines += ["", "<i>Ex:</i> {}".format(ex)]
    if w["translation"]:
        lines += ["", "🇷🇺 {}".format(esc(w["translation"]))]
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
    pro = bool(s["is_self"]) and bool(word["definition"])
    head = "📚 Осталось: {}".format(due_count(sid))
    front = word["definition"] if pro else word["term"]
    if not show:
        return "{}\n\n{}".format(head, esc(front)), [
            [("👀 Показать", "w_show:%d:%d" % (sid, word["id"]))],
            [("⬅️ Выйти", "lrn:%d" % sid)]]
    text = "{}\n\n{}\n➖➖➖\n{}".format(head, esc(front), card_back(word, pro))
    labels = (("Снова", 0), ("Трудно", 1), ("Хорошо", 2), ("Легко", 3))
    rows = [[("{} · {}".format(n, ivl_label(preview_ivl(word, g))),
              "w_g:%d:%d:%d" % (sid, word["id"], g)) for n, g in labels[:2]],
            [("{} · {}".format(n, ivl_label(preview_ivl(word, g))),
              "w_g:%d:%d:%d" % (sid, word["id"], g)) for n, g in labels[2:]],
            [("⬅️ Выйти", "lrn:%d" % sid)]]
    return text, rows


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
               "lrn_pet", "lrn_petname", "lrn_ex", "lrn_exgo",
               "lrn_words", "lrn_more",
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
                        "<code>apple - яблоко\nto give up - сдаться</code>",
                        [[("⬅️ Назад", "lrn:%d" % sid)]])
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
            t, r = screen_ex(sid)
            return edit(chat_id, message_id, t, r)
        if cmd == "lrn_exgo":
            kind = parts[2]
            s_ = sget(sid)
            if (s_["keys"] or 0) < 1:
                return toast(cq_id, "Нужен ключик")
            toast(cq_id, "Составляю задание…")
            edit(chat_id, message_id, "🎁 Составляю задание по вашим словам…", [])
            data, why = ai_exercise(sid, kind)
            if not data:
                t, r = screen_ex(sid)
                return edit(chat_id, message_id, "⚠️ " + esc(why) + "\n\n" + t, r)
            run("UPDATE students SET keys=MAX(COALESCE(keys,0)-1,0) WHERE id=?", (sid,))
            set_state(chat_id, student_id=sid,
                      pending={"action": "exdo", "sid": sid, "kind": kind,
                               "items": data["items"]})
            return edit(chat_id, message_id, ex_text(data),
                        [[("🚫 Отменить", "lrn:%d" % sid)]])
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
        t, r = screen_student(sid)
        return edit(chat_id, message_id, t, [[("✍️ Добавить тему", "note:%d:%d" % (sid, lid))]] + r)

    if cmd == "doned":
        set_state(chat_id, student_id=sid, pending={"action": "lesson_date", "sid": sid})
        return edit(chat_id, message_id, "Какой датой записать занятие?\nНапример: 15.09 или вчера",
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "note":
        set_state(chat_id, student_id=sid,
                  pending={"action": "note", "sid": sid, "lid": int(parts[2])})
        return edit(chat_id, message_id, "Что прошли на занятии? (тема, ДЗ)",
                    [[("⬅️ Пропустить", "st:%d" % sid)]])

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

    if cmd == "warm":
        body = None
        if AI_KEY:
            flash(chat_id, "🤖 Генерирую warm-up…")
            ai = ai_warmup(sid)
            if ai:
                body = "🔥 <b>Warm-up — {}</b>\n\n{}".format(esc(sget(sid)["name"]), esc(ai))
            else:
                flash(chat_id, "ИИ недоступен — собрала разминку по шаблону.")
        send(chat_id, body or text_warmup(sid))
        t, r = screen_student(sid)
        return edit(chat_id, message_id, t, r)

    if cmd == "report":
        edit(chat_id, message_id, "📊 Собираю сводку…", [])
        body = text_weekly_report(sid)
        return edit(chat_id, message_id,
                    body or "За последнюю неделю у ученика нет ни повторений, ни упражнений.",
                    [[("⬅️ Назад", "st:%d" % sid)]])

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
                 ("📊 Сводка за неделю", "report:%d" % sid)],
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
        send(chat_id, "🔎 Проверяю…")
        res = ai_check(sid, pending.get("kind", ""), items, answers)
        if not res:
            run("UPDATE students SET keys=COALESCE(keys,0)+1 WHERE id=?", (sid,))
            return send(chat_id, "⚠️ ИИ не ответил, ключик вернула. Попробуйте позже.",
                        [[("⬅️ В меню", "lrn:%d" % sid)]])
        run("INSERT INTO ex_log (on_date, student_id, kind, tasks, answers, feedback) "
            "VALUES (?,?,?,?,?,?)",
            (today().isoformat(), sid, pending.get("kind", ""),
             "\n".join(it["q"] for it in items)[:2000],
             "\n".join(answers)[:2000], res[:2000]))
        return send(chat_id, "📝 <b>Разбор</b>\n\n" + esc(res),
                    [[("🎁 Ещё упражнение", "lrn_ex:%d" % sid)],
                     [("⬅️ В меню", "lrn:%d" % sid)]])

    if action == "petname":
        name = " ".join(text.split())[:24]
        set_state(chat_id, pending=None)
        if not name:
            return send(chat_id, "Имя не распозналось, попробуйте ещё раз.")
        run("UPDATE students SET pet_name=? WHERE id=?", (name, sid))
        t, r = screen_pet(sid)
        return send(chat_id, "✅ Теперь питомца зовут <b>{}</b>.\n\n".format(esc(name)) + t, r)

    if action == "words":
        pairs = parse_words(text)
        if not pairs:
            return send(chat_id, "Не разобрала. Формат: <code>apple - яблоко</code>, "
                                 "по одному слову в строке.")
        n = add_words(sid, pairs, pending.get("by", "педагог"))
        set_state(chat_id, pending=None)
        flash(chat_id, "✅ Добавлено слов: <b>{}</b>. Первое повторение — сегодня.".format(n))
        if pending.get("by") == "ученик":
            owner = None if sget(sid)["is_guest"] else owner_chat(sid)
            if owner:
                send(owner, "📚 <b>{}</b> добавил(а) {} новых слов в словарь.".format(
                    esc(sget(sid)["name"]), n))
            t, r = screen_learner(sid)
        else:
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
        sent = notify_student(sid, "📝 <b>Домашнее задание</b>{}\n\n{}".format(
            " к занятию " + fmt_date(due) if due else "", esc(text.strip()[:2000])))
        flash(chat_id, "✅ Домашка сохранена{}.".format(
            " и отправлена ученику" if sent else " (ученик не подключён к боту)"))
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

    if cmd in ("ai", "ии", "токены"):
        return send(chat_id, text_ai_usage(), [[("⬅️ К ученикам", "menu")]])

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
        if msg.get("document"):
            if not is_owner(user_id):
                return
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
        {"command": "ai", "description": "Расход токенов ИИ"},
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
                    pet_jobs, streak_keys, weekly_board, weekly_report, auto_backup):
            try:
                job()
            except Exception:
                traceback.print_exc()
        if not res.get("result"):
            time.sleep(1)


if __name__ == "__main__":
    main()
