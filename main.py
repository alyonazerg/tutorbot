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
API = "https://api.telegram.org/bot" + TOKEN + "/"
CURRENCY = "₽"
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WD_CAP = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
RATE_PRESETS = [(2000, 60), (1500, 45)]
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
    "/week — расписание на неделю\n"
    "/month — итоги месяца\n"
    "/export — выгрузка в CSV\n"
    "/id — ваш Telegram ID"
)


# --------------------------------------------------------------------------- API

def tg(method, **params):
    data = json.dumps(params, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API + method, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=70) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode("utf-8", "replace")[:400])
    except Exception as e:
        print("API error:", e)
    return {}


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


def markup(rows):
    if not rows:
        return None
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


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
CREATE TABLE IF NOT EXISTS state (
    chat_id INTEGER PRIMARY KEY, student_id INTEGER, pending TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""

MIGRATIONS = [
    ("students", "duration", "INTEGER DEFAULT 60"),
    ("students", "tg_user_id", "INTEGER"),
    ("students", "code", "TEXT"),
    ("students", "code_kid", "TEXT"),
    ("students", "access", "TEXT DEFAULT 'full'"),
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
    return q("SELECT * FROM students WHERE chat_id=? AND archived=? ORDER BY name",
             (chat_id, 1 if archived else 0))


def student(sid):
    return q("SELECT * FROM students WHERE id=?", (sid,), one=True)


def student_by_user(user_id):
    return q("SELECT * FROM students WHERE tg_user_id=?", (user_id,), one=True)


def owner_chat(sid):
    s = student(sid)
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
    return q("SELECT * FROM words WHERE student_id=? AND due<=? ORDER BY due, id LIMIT ?",
             (sid, today().isoformat(), limit))


def due_count(sid):
    return q("SELECT COUNT(*) c FROM words WHERE student_id=? AND due<=?",
             (sid, today().isoformat()), one=True)["c"]


def word_count(sid):
    return q("SELECT COUNT(*) c FROM words WHERE student_id=?", (sid,), one=True)["c"]


def grade_word(word_id, grade):
    """grade: 0 — не помню, 1 — помню, 2 — легко. Упрощённый SM-2."""
    w = q("SELECT * FROM words WHERE id=?", (word_id,), one=True)
    if not w:
        return None
    ease = w["ease"] or 2.5
    ivl = w["ivl"] or 0
    reps = w["reps"] or 0
    lapses = w["lapses"] or 0
    if grade == 0:
        ease, ivl, lapses = max(1.3, ease - 0.2), 0, lapses + 1
    elif grade == 1:
        ivl = 1 if reps == 0 else max(1, int(round(ivl * ease)))
        reps += 1
    else:
        ease = min(3.0, ease + 0.15)
        ivl = 3 if reps == 0 else max(2, int(round(ivl * ease * 1.3)))
        reps += 1
    due = (today() + timedelta(days=ivl)).isoformat()
    run("UPDATE words SET ease=?, ivl=?, reps=?, lapses=?, due=? WHERE id=?",
        (ease, ivl, reps, lapses, due, word_id))
    return ivl


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
    rows.append([("🗄 Архив", "arch_list"), ("📁 CSV", "export")])
    text = ("👩‍🏫 <b>Ученики</b>\nРядом с именем — остаток оплаченных занятий.\n"
            "⚠️ оплата закончилась · 🔸 остался один урок")
    if not students(chat_id):
        text = "Учеников пока нет. Добавьте первого 👇"
    return text, rows


def screen_student(sid):
    s = student(sid)
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
    occ = occurrences(sid, max(st["left"], 3))
    if occ:
        lines.append("Ближайшие: " + ", ".join(
            "{} {}{}".format(fmt_date(d, True), t, KIND_MARK.get(k, "")).strip()
            for d, t, k in occ[:3]))
        if st["left"] > 0 and len(occ) >= st["left"]:
            lines.append("Оплаченных хватит до <b>{}</b>".format(fmt_date(occ[st["left"] - 1][0])))
    total = word_count(sid)
    if total:
        lines.append("Словарь: {} слов, на сегодня {}".format(total, due_count(sid)))
    if s["tg_user_id"]:
        lines.append("Ученик подключён к боту ✅")

    rows = [
        [("✅ Провела", "done:%d" % sid), ("📅 Другой датой", "doned:%d" % sid)],
        [("💰 Оплата", "pay:%d" % sid), ("🚫 Отмена урока", "cancel:%d" % sid)],
        [("🔁 Перенести", "move:%d" % sid), ("🗓 Расписание", "sched:%d" % sid)],
        [("📚 Слова", "words:%d" % sid), ("📋 История", "hist:%d" % sid)],
        [("📤 Ученику", "share:%d" % sid), ("⚙️ Ещё", "more:%d" % sid)],
        [("⬅️ К ученикам", "menu")],
    ]
    return "\n".join(lines), rows


def screen_pay(sid):
    s = student(sid)
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


def screen_sched(sid):
    s = student(sid)
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
    s = student(sid)
    ls = q("SELECT * FROM lessons WHERE student_id=? ORDER BY held_on DESC, id DESC LIMIT 15", (sid,))
    ps = q("SELECT * FROM payments WHERE student_id=? ORDER BY id DESC LIMIT 10", (sid,))
    mv = q("SELECT * FROM moves WHERE student_id=? AND to_date>=? ORDER BY to_date",
           (sid, today().isoformat()))
    lines = ["📋 <b>{}</b>".format(esc(s["name"])), "", "<b>Занятия</b>"]
    if ls:
        for l in ls:
            icon = "✅" if l["kind"] == "held" else ("🚫" if l["charged"] else "⭕️")
            lines.append("{} {}{}".format(icon, fmt_date(l["held_on"]),
                                          " — " + esc(l["note"]) if l["note"] else ""))
    else:
        lines.append("пока нет")
    lines += ["", "<b>Оплаты</b>"]
    if ps:
        for p in ps:
            lines.append("💰 {} — {} за {} зан.".format(
                fmt_date(p["paid_on"]), fmt_money(p["amount"]), p["lessons"]))
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
    s = student(sid)
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
    s = student(sid)
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
    occ = occurrences(sid, 3)
    if occ:
        lines += ["", "Ближайшие занятия: " + ", ".join(
            "{} {}".format(fmt_date(d, True), t).strip() for d, t, _ in occ)]
    return "\n".join(lines)


def text_reminder(sid):
    s = student(sid)
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
    s = student(sid)
    occ = occurrences(sid, max(stats(sid)["left"], 4))
    if not occ:
        return "Расписание для {} пока не задано.".format(esc(s["name"]))
    body = "\n".join("{:<4}{:<8}{}".format(WD_CAP[d.weekday()], fmt_date(d, True),
                                           (t or "") + KIND_WORD.get(k, ""))
                     for d, t, k in occ[:10])
    return "🗓 <b>Расписание — {}</b>\n".format(esc(s["name"])) + pre(body)


def text_invite(sid, kind="full"):
    s = student(sid)
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
                "нужно нажимать «не помню / помню / легко».")
        head = "🔗 <b>Код для ребёнка</b> (только словарь)"
    return ("{}\n\nПерешлите ученику:\n\n"
            "Открой {} , нажми Start и отправь код: <code>{}</code>\n\n{}".format(
                head, link, code, what))


def text_when(sid):
    s = student(sid)
    occ = occurrences(sid, 8)
    if not occ:
        return ("🗓 Ближайшие занятия пока не назначены.\n"
                "Преподаватель добавит даты — они появятся здесь.")
    body = "\n".join("{:<4}{:<8}{}".format(WD_CAP[d.weekday()], fmt_date(d, True),
                                           (t or "") + KIND_WORD.get(k, ""))
                     for d, t, k in occ)
    return "🗓 <b>Ближайшие занятия — {}</b>\n".format(esc(s["name"])) + pre(body)


# ----------------------------------------------------------------- Экраны ученика

def screen_learner(sid):
    s = student(sid)
    if (s["access"] or "full") == "kid":
        total, due = word_count(sid), due_count(sid)
        lines = ["👋 <b>{}</b>".format(esc(s["name"])), "",
                 "📚 Слов в словаре: <b>{}</b>".format(total),
                 "На повторение сегодня: <b>{}</b>".format(due)]
        rows = [[("🔁 Повторить слова ({})".format(due), "lrn_go:%d" % sid)],
                [("➕ Добавить слова", "lrn_add:%d" % sid)],
                [("📖 Мои слова", "lw:%d" % sid)],
                [("🔄 Обновить", "lrn:%d" % sid)]]
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
    rows = [[("🗓 Когда занятия", "lrn_when:%d" % sid)],
            [("🔁 Повторить слова ({})".format(due), "lrn_go:%d" % sid)],
            [("➕ Добавить слова", "lrn_add:%d" % sid),
             ("📖 Мои слова", "lw:%d" % sid)],
            [("🔄 Обновить", "lrn:%d" % sid)]]
    return "\n".join(lines), rows


def screen_card(sid, word, show=False):
    if not word:
        return ("🎉 На сегодня всё — слов на повторение больше нет.\n"
                "Всего в словаре: {} слов.".format(word_count(sid)),
                [[("⬅️ В меню", "lrn:%d" % sid)]])
    head = "📚 Осталось: {}\n\n<b>{}</b>".format(due_count(sid), esc(word["term"]))
    if not show:
        return head, [[("👀 Показать", "w_show:%d:%d" % (sid, word["id"]))],
                      [("⬅️ Выйти", "lrn:%d" % sid)]]
    text = head + "\n\n<b>{}</b>".format(esc(word["translation"]))
    rows = [[("❌ Не помню", "w_g:%d:%d:0" % (sid, word["id"])),
             ("🙂 Помню", "w_g:%d:%d:1" % (sid, word["id"])),
             ("😎 Легко", "w_g:%d:%d:2" % (sid, word["id"]))],
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

def record_lesson(chat_id, sid, d, kind="held", charged=1):
    lid = run("INSERT INTO lessons (student_id, held_on, kind, charged) VALUES (?,?,?,?)",
              (sid, d.isoformat(), kind, charged))
    s = student(sid)
    st = stats(sid)
    what = "Занятие" if kind == "held" else (
        "Отмена со списанием" if charged else "Отмена без списания")
    send(chat_id, "✅ {} — <b>{}</b>, {}.\nОстаток: <b>{}</b> {}.".format(
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
    if cmd in ("lrn", "lrn_go", "lrn_add", "lrn_when", "lw", "lw_back", "lwdl",
               "w_show", "w_g"):
        learner = student_by_user(user_id)
        if learner and not is_owner(user_id):
            sid = learner["id"]
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
        if cmd == "lrn_when":
            toast(cq_id)
            return edit(chat_id, message_id, text_when(sid),
                        [[("⬅️ Назад", "lrn:%d" % sid)]])
        if cmd in ("lw", "lw_back"):
            toast(cq_id)
            t, r = screen_wpick(sid, learner=True)
            return edit(chat_id, message_id, t, r)
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
            toast(cq_id, "Следующий повтор через {} дн.".format(ivl) if ivl else "Повторим сегодня")
            ws = due_words(sid, 1)
            t, r = screen_card(sid, ws[0] if ws else None)
            return edit(chat_id, message_id, t, r)

    if not is_owner(user_id):
        return toast(cq_id, "Эта кнопка только для преподавателя")

    toast(cq_id)

    def show(fn, *a):
        t, r = fn(*a)
        edit(chat_id, message_id, t, r)

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
        record_lesson(chat_id, sid, today(), kind="cancel", charged=1 if cmd == "canc1" else 0)
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
            send(chat_id, "↩️ Запись от {} удалена. Остаток: <b>{}</b>.".format(
                fmt_date(last["held_on"]), stats(sid)["left"]))
        else:
            send(chat_id, "Записей нет.")
        return show(screen_student, sid)

    if cmd == "undopay":
        last = q("SELECT * FROM payments WHERE student_id=? ORDER BY id DESC LIMIT 1", (sid,), one=True)
        if last:
            run("DELETE FROM payments WHERE id=?", (last["id"],))
            send(chat_id, "↩️ Оплата {} удалена. Остаток: <b>{}</b>.".format(
                fmt_money(last["amount"]), stats(sid)["left"]))
        else:
            send(chat_id, "Оплат нет.")
        return show(screen_student, sid)

    if cmd == "pay":
        return show(screen_pay, sid)

    if cmd == "payn":
        n = int(parts[2])
        s = student(sid)
        if s["rate"]:
            run("INSERT INTO payments (student_id, lessons, amount, paid_on) VALUES (?,?,?,?)",
                (sid, n, n * s["rate"], today().isoformat()))
            send(chat_id, "✅ Оплата — <b>{}</b>: {} {} · {} · {}.\nОстаток: <b>{}</b>.".format(
                esc(s["name"]), n, plural(n), fmt_money(n * s["rate"]), fmt_date(today()),
                stats(sid)["left"]))
            return show(screen_student, sid)
        set_state(chat_id, student_id=sid, pending={"action": "amount", "sid": sid, "lessons": n})
        return edit(chat_id, message_id,
                    "Пакет {} зан.\nНапишите сумму (например 4000), можно с датой: 4000 12.09.\n"
                    "Без суммы — «-».".format(n), [[("⬅️ Назад", "st:%d" % sid)]])

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
        send(chat_id, "🧹 Убрано разовых дат: <b>{}</b>.".format(n))
        return show(screen_sched, sid)

    if cmd == "hist":
        return show(screen_history, sid)

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
            send(chat_id, "🗑 Слово удалено: <b>{}</b> — {}.".format(
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
        send(chat_id, text)
        _t, r = screen_share(sid)
        return edit(chat_id, message_id,
                    text + "\n\n⬇️ Это же сообщение продублировано внизу чата — "
                           "его можно переслать ученику.", r)

    if cmd == "more":
        s = student(sid)
        rows = [[("💵 Ставка за занятие", "rate:%d" % sid)],
                [("🔗 Код: взрослый", "code:%d" % sid),
                 ("🔗 Код: ребёнок", "codek:%d" % sid)],
                [("✏️ Переименовать", "ren:%d" % sid)],
                [("↩️ Убрать последнее занятие", "undo:%d" % sid)],
                [("↩️ Убрать последнюю оплату", "undopay:%d" % sid)],
                [("🗄 В архив", "arch:%d" % sid)],
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
        send(chat_id, "✅ Ставка для <b>{}</b>: {} / {} мин.".format(
            esc(student(sid)["name"]), fmt_money(float(parts[2])), parts[3]))
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
        name = student(sid)["name"]
        run("UPDATE students SET archived=1 WHERE id=?", (sid,))
        send(chat_id, "🗄 <b>{}</b> в архиве, данные сохранены.".format(esc(name)))
        return show(screen_students, chat_id)

    if cmd == "unarch":
        run("UPDATE students SET archived=0 WHERE id=?", (sid,))
        send(chat_id, "✅ <b>{}</b> снова в списке.".format(esc(student(sid)["name"])))
        return show(screen_student, sid)


# -------------------------------------------------------------------- Ввод текстом

def handle_pending(chat_id, pending, text, user_id=None):
    action = pending.get("action")
    sid = pending.get("sid")

    if action == "words":
        pairs = parse_words(text)
        if not pairs:
            return send(chat_id, "Не разобрала. Формат: <code>apple - яблоко</code>, "
                                 "по одному слову в строке.")
        n = add_words(sid, pairs, pending.get("by", "педагог"))
        set_state(chat_id, pending=None)
        send(chat_id, "✅ Добавлено слов: <b>{}</b>. Первое повторение — сегодня.".format(n))
        if pending.get("by") == "ученик":
            owner = owner_chat(sid)
            if owner:
                send(owner, "📚 <b>{}</b> добавил(а) {} новых слов в словарь.".format(
                    esc(student(sid)["name"]), n))
            t, r = screen_learner(sid)
        else:
            t, r = screen_words(sid)
        return send(chat_id, t, r)

    if action == "new_student":
        name = text.strip()[:60]
        new_id = run("INSERT INTO students (chat_id, name) VALUES (?,?)", (chat_id, name))
        set_state(chat_id, student_id=new_id, pending=None)
        send(chat_id, "✅ Ученик <b>{}</b> добавлен.".format(esc(name)))
        t, r = screen_student(new_id)
        return send(chat_id, t, r)

    if action == "rename":
        old = student(sid)["name"]
        new = text.strip()[:60]
        run("UPDATE students SET name=? WHERE id=?", (new, sid))
        set_state(chat_id, pending=None)
        send(chat_id, "✅ {} → <b>{}</b>.".format(esc(old), esc(new)))
        t, r = screen_student(sid)
        return send(chat_id, t, r)

    if action == "rate":
        nums = re.findall(r"\d+", text)
        if not nums:
            return send(chat_id, "Нужно число, например 1800 или «1800 50».")
        rate = float(nums[0])
        dur = int(nums[1]) if len(nums) > 1 else (student(sid)["duration"] or 60)
        run("UPDATE students SET rate=?, duration=? WHERE id=?", (rate, dur, sid))
        set_state(chat_id, pending=None)
        send(chat_id, "✅ Ставка: {} / {} мин.".format(fmt_money(rate), dur))
        t, r = screen_student(sid)
        return send(chat_id, t, r)

    if action == "note":
        run("UPDATE lessons SET note=? WHERE id=?", (text.strip()[:200], pending["lid"]))
        set_state(chat_id, pending=None)
        send(chat_id, "✅ Тема записана: {}".format(esc(text.strip()[:200])))
        t, r = screen_student(sid)
        return send(chat_id, t, r)

    if action == "custom_lessons":
        m = re.search(r"\d+", text)
        if not m:
            return send(chat_id, "Нужно число занятий, например 6.")
        n = int(m.group())
        s = student(sid)
        if s["rate"]:
            run("INSERT INTO payments (student_id, lessons, amount, paid_on) VALUES (?,?,?,?)",
                (sid, n, n * s["rate"], today().isoformat()))
            set_state(chat_id, pending=None)
            send(chat_id, "✅ Оплата: {} {} · {}. Остаток: <b>{}</b>.".format(
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
            digits = re.sub(r"[^\d.,]", "", raw).replace(",", ".")
            amount = float(digits) if digits.strip(".") else 0.0
        run("INSERT INTO payments (student_id, lessons, amount, paid_on) VALUES (?,?,?,?)",
            (sid, n, amount, d.isoformat()))
        set_state(chat_id, pending=None)
        send(chat_id, "✅ Оплата — <b>{}</b>: {} {} · {} · {}.\nОстаток: <b>{}</b>.".format(
            esc(student(sid)["name"]), n, plural(n), fmt_money(amount), fmt_date(d),
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
        send(chat_id, "✅ Перенос: {} → <b>{} {}</b>.".format(
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
        send(chat_id, "✅ Добавлены даты: {}".format(
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
        send(chat_id, "✅ Расписание: {}".format(slots_text(sid) or "очищено"))
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

    if cmd == "id":
        return send(chat_id, "Ваш Telegram ID: <code>{}</code>".format(user_id))

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

    if cmd in ("week", "неделя"):
        t, r = screen_week(chat_id)
        return send(chat_id, t, r)

    if cmd in ("schedule", "расписание"):
        t, r = screen_schedule_all(chat_id)
        return send(chat_id, t, r)

    if cmd == "export":
        return export_csv(chat_id)

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

def learner_flow(chat_id, user_id, text):
    s = student_by_user(user_id)
    if not s:
        code = re.sub(r"[^A-Za-z0-9]", "", text).upper()[:6]
        found = access = None
        if code:
            found = q("SELECT * FROM students WHERE code=? AND code IS NOT NULL",
                      (code,), one=True)
            access = "full"
            if not found:
                found = q("SELECT * FROM students WHERE code_kid=? AND code_kid IS NOT NULL",
                          (code,), one=True)
                access = "kid"
        if not found:
            return send(chat_id, "👋 Это бот вашего преподавателя.\n\n"
                                 "Отправьте код, который вам дали, — и увидите словарь "
                                 "для повторения (а если код полный — ещё и свои занятия).")
        run("UPDATE students SET tg_user_id=?, access=? WHERE id=?",
            (user_id, access, found["id"]))
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

def daily_digest():
    if not DIGEST_HOUR:
        return
    now = datetime.now()
    if now.hour < DIGEST_HOUR or meta_get("digest_date") == today().isoformat():
        return
    meta_set("digest_date", today().isoformat())

    for row in q("SELECT DISTINCT chat_id FROM students"):
        chat_id = row["chat_id"]
        items = []
        for s in students(chat_id):
            st = stats(s["id"])
            for d, t, k in occurrences(s["id"], 3):
                if d != today():
                    break
                items.append(" {:<6}{:<12}{}".format(
                    t or "--:--", s["name"][:12],
                    KIND_WORD.get(k, "").strip() + " " +
                    ("оплата!" if st["left"] <= 0 else "")))
        if items:
            send(chat_id, "☀️ <b>Сегодня занятия</b>\n" + pre("\n".join(items)))

    for s in q("SELECT * FROM students WHERE tg_user_id IS NOT NULL AND archived=0"):
        n = due_count(s["id"])
        if n:
            send(s["tg_user_id"], "📚 Пора повторить слова: сегодня <b>{}</b>.".format(n),
                 [[("🔁 Начать", "lrn_go:%d" % s["id"])]])


# --------------------------------------------------------------------- Диспетчер

def is_owner(user_id):
    return OWNER_ID == 0 or user_id == OWNER_ID


def handle(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg.get("from", {}).get("id")
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
            return handle_pending(chat_id, pending, text, user_id)
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


def main():
    if not TOKEN:
        raise SystemExit("Задайте токен: export TG_BOT_TOKEN='...'")
    db().close()
    me = tg("getMe").get("result", {})
    if me.get("username"):
        meta_set("username", me["username"])
    print("Бот запущен: @" + str(me.get("username")))
    tg("setMyCommands", commands=[
        {"command": "students", "description": "Ученики"},
        {"command": "week", "description": "Ближайшая неделя"},
        {"command": "schedule", "description": "Моё расписание"},
        {"command": "month", "description": "Итоги месяца"},
        {"command": "export", "description": "Выгрузка CSV"},
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
        try:
            daily_digest()
        except Exception:
            traceback.print_exc()
        if not res.get("result"):
            time.sleep(1)


if __name__ == "__main__":
    main()
