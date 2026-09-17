#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот для репетитора: ученики, пакеты, оплаты, занятия, расписание.

Возможности:
  - несколько учеников, переключение кнопками, архив;
  - пакеты 1 / 4 / 8 / своё число, ставка за занятие и автоподсчёт суммы;
  - оплаты: количество занятий + сумма + дата;
  - отметка проведённых занятий (сегодня / другой датой), тема занятия и ДЗ;
  - отмена занятия со списанием и без;
  - остаток оплаченных занятий, долг, если провели больше оплаченного;
  - расписание («пн 17:00, чт 18:30») и прогноз, когда закончится пакет;
  - готовые сообщения для пересылки ученику: выписка, напоминание об оплате,
    расписание ближайших занятий;
  - итоги месяца по всем ученикам;
  - утренний дайджест «сегодня занятия у ...»;
  - экспорт всех занятий и оплат в CSV.

Запуск:
  1) Получить токен у @BotFather.
  2) export TG_BOT_TOKEN="123456:AA..."
     export TG_OWNER_ID="ваш_telegram_id"   # узнать: напишите боту /id
     export TG_DIGEST_HOUR="9"              # час утреннего дайджеста, 0 = выключить
  3) python3 tutor_bot_tg.py

Зависимостей нет — только стандартная библиотека Python 3.8+.
Данные в SQLite-файле tutor_tg.db рядом со скриптом.
"""

import csv
import html
import io
import json
import os
import re
import sqlite3
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

HELP = (
    "👩‍🏫 <b>Учёт занятий и оплат</b>\n\n"
    "Всё делается кнопками. Быстрые команды:\n"
    "/students — список учеников\n"
    "/new Аня — добавить ученика\n"
    "/s Аня — открыть карточку\n"
    "/done — занятие сегодня, /done 15.09 — датой\n"
    "/pay 4 4000 — оплата: 4 занятия, 4000\n"
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
    """Отправка файла через multipart/form-data без внешних библиотек."""
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


def send(chat_id, text, rows=None, preview=False):
    return tg("sendMessage", chat_id=chat_id, text=text[:4000], parse_mode="HTML",
              reply_markup=markup(rows), disable_web_page_preview=not preview)


def edit(chat_id, message_id, text, rows=None):
    res = tg("editMessageText", chat_id=chat_id, message_id=message_id, text=text[:4000],
             parse_mode="HTML", reply_markup=markup(rows), disable_web_page_preview=True)
    if not res.get("ok"):
        return send(chat_id, text, rows)
    return res


def esc(s):
    return html.escape(str(s or ""))


# ------------------------------------------------------------------------ Хранилище

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
CREATE TABLE IF NOT EXISTS state (
    chat_id INTEGER PRIMARY KEY, student_id INTEGER, pending TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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


def stats(sid):
    p = q("SELECT COALESCE(SUM(lessons),0) l, COALESCE(SUM(amount),0) a "
          "FROM payments WHERE student_id=?", (sid,), one=True)
    held = q("SELECT COUNT(*) c FROM lessons WHERE student_id=? AND charged=1",
             (sid,), one=True)["c"]
    free = q("SELECT COUNT(*) c FROM lessons WHERE student_id=? AND charged=0",
             (sid,), one=True)["c"]
    return {"paid_lessons": p["l"], "paid_amount": p["a"], "held": held,
            "free": free, "left": p["l"] - held}


# ------------------------------------------------------------------------ Утилиты

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


def plural(n, forms=("занятие", "занятия", "занятий")):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def fmt_money(x):
    return "{:,.0f}".format(x or 0).replace(",", " ") + " " + CURRENCY


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


def next_dates(sid, count, start=None):
    slots = q("SELECT weekday, at FROM slots WHERE student_id=? ORDER BY weekday, at", (sid,))
    if not slots or count <= 0:
        return []
    cur = start or today()
    out = []
    for _ in range(400):
        for s in slots:
            if s["weekday"] == cur.weekday():
                out.append((cur, s["at"]))
                if len(out) >= count:
                    return out
        cur += timedelta(days=1)
    return out


# -------------------------------------------------------------------------- Экраны

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
    rows.append([("🗓 Неделя", "week"), ("🗄 Архив", "arch_list"), ("📁 CSV", "export")])
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
    lastpay = q("SELECT * FROM payments WHERE student_id=? ORDER BY id DESC LIMIT 1",
                (sid,), one=True)

    lines = ["👤 <b>{}</b>".format(esc(s["name"])), ""]
    lines.append("Проведено: <b>{}</b>".format(st["held"]))
    lines.append("Оплачено занятий: <b>{}</b>".format(st["paid_lessons"]))
    if st["left"] >= 0:
        lines.append("Остаток: <b>{}</b> {}".format(st["left"], "✅" if st["left"] else "⚠️"))
    else:
        debt = -st["left"]
        extra = " (≈ {})".format(fmt_money(debt * s["rate"])) if s["rate"] else ""
        lines.append("Долг: <b>{} зан.</b>{} ⚠️".format(debt, extra))
    if st["free"]:
        lines.append("Без списания: {}".format(st["free"]))
    lines.append("Оплат всего: {}".format(fmt_money(st["paid_amount"])))
    if s["rate"]:
        lines.append("Ставка: {}".format(fmt_money(s["rate"])))
    if last:
        tag = "" if last["kind"] == "held" else " (отмена)"
        note = " — " + esc(last["note"]) if last["note"] else ""
        lines.append("Последнее: {}{}{}".format(fmt_date(last["held_on"]), tag, note))
    if lastpay:
        lines.append("Последняя оплата: {} за {} зан. — {}".format(
            fmt_money(lastpay["amount"]), lastpay["lessons"], fmt_date(lastpay["paid_on"])))
    sl = slots_text(sid)
    if sl:
        lines.append("Расписание: " + sl)
        nxt = next_dates(sid, max(st["left"], 1))
        if nxt:
            lines.append("Ближайшие: " + ", ".join(
                "{} {}".format(fmt_date(d, True), t).strip() for d, t in nxt[:3]))
            if st["left"] > 0:
                lines.append("Оплаченных хватит до <b>{}</b>".format(fmt_date(nxt[-1][0])))

    rows = [
        [("✅ Провела", "done:%d" % sid), ("📅 Другой датой", "doned:%d" % sid)],
        [("💰 Оплата", "pay:%d" % sid), ("🚫 Отмена урока", "cancel:%d" % sid)],
        [("🗓 Расписание", "sched:%d" % sid), ("📋 История", "hist:%d" % sid)],
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
    hint = "\nСтавка задана — можно записать оплату одним нажатием." if rate else \
           "\nПодсказка: задайте ставку в «⚙️ Ещё», тогда сумма посчитается сама."
    return "💰 <b>Оплата — {}</b>\nСколько занятий оплачено?{}".format(esc(s["name"]), hint), rows


def screen_history(sid):
    s = student(sid)
    ls = q("SELECT * FROM lessons WHERE student_id=? ORDER BY held_on DESC, id DESC LIMIT 15", (sid,))
    ps = q("SELECT * FROM payments WHERE student_id=? ORDER BY id DESC LIMIT 10", (sid,))
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
    return "\n".join(lines), [[("⬅️ Назад", "st:%d" % sid)]]


def screen_month(chat_id):
    first = today().replace(day=1).isoformat()
    lines = ["📊 <b>Итоги месяца ({})</b>".format(today().strftime("%m.%Y")), ""]
    money = lessons = 0
    for s in students(chat_id):
        held = q("SELECT COUNT(*) c FROM lessons WHERE student_id=? AND held_on>=? AND kind='held'",
                 (s["id"], first), one=True)["c"]
        paid = q("SELECT COALESCE(SUM(amount),0) a FROM payments WHERE student_id=? AND paid_on>=?",
                 (s["id"], first), one=True)["a"]
        st = stats(s["id"])
        money += paid
        lessons += held
        lines.append("{}: {} зан. · {} · остаток {}".format(
            esc(s["name"]), held, fmt_money(paid), st["left"]))
    lines += ["", "Занятий: <b>{}</b>".format(lessons), "Оплат: <b>{}</b>".format(fmt_money(money))]
    return "\n".join(lines), [[("⬅️ К ученикам", "menu")]]


def screen_week(chat_id):
    """Расписание на 7 дней по всем ученикам."""
    plan = {}
    for s in students(chat_id):
        for d, t in next_dates(s["id"], 20):
            if (d - today()).days > 6:
                break
            plan.setdefault(d, []).append((t, s["name"], stats(s["id"])["left"]))
    lines = ["🗓 <b>Ближайшая неделя</b>", ""]
    if not plan:
        lines.append("Расписание не задано ни у кого.")
    for d in sorted(plan):
        lines.append("<b>{} {}</b>".format(WEEKDAYS[d.weekday()], fmt_date(d, True)))
        for t, name, left in sorted(plan[d]):
            warn = " ⚠️" if left <= 0 else ""
            lines.append("  {} {}{}".format(t or "—", esc(name), warn))
    return "\n".join(lines), [[("⬅️ К ученикам", "menu")]]


def screen_archive(chat_id):
    rows = [[(s["name"], "unarch:%d" % s["id"])] for s in students(chat_id, archived=True)]
    rows.append([("⬅️ К ученикам", "menu")])
    text = "🗄 <b>Архив</b>\nНажмите, чтобы вернуть ученика в список."
    if len(rows) == 1:
        text = "🗄 Архив пуст."
    return text, rows


# --------------------------------------------------- Сообщения для пересылки ученику

def text_statement(sid, with_money=True):
    s = student(sid)
    st = stats(sid)
    ls = q("SELECT * FROM lessons WHERE student_id=? ORDER BY held_on DESC, id DESC LIMIT 5", (sid,))
    lines = ["📄 <b>{}</b> — занятия на {}".format(esc(s["name"]), fmt_date(today())), ""]
    lines.append("Проведено: {}".format(st["held"]))
    lines.append("Оплачено: {}".format(st["paid_lessons"]))
    lines.append("Остаток: <b>{}</b>".format(st["left"]) if st["left"] >= 0
                 else "К оплате: <b>{} зан.</b>".format(-st["left"]))
    if ls:
        lines += ["", "Последние занятия:"]
        for l in ls:
            mark = "" if l["kind"] == "held" else " (отмена)"
            lines.append("• {}{}{}".format(fmt_date(l["held_on"], True), mark,
                                           " — " + esc(l["note"]) if l["note"] else ""))
    nxt = next_dates(sid, 3)
    if nxt:
        lines += ["", "Ближайшие занятия: " + ", ".join(
            "{} {}".format(fmt_date(d, True), t).strip() for d, t in nxt)]
    if with_money and st["paid_amount"]:
        lines += ["", "Оплачено всего: {}".format(fmt_money(st["paid_amount"]))]
    return "\n".join(lines)


def text_reminder(sid):
    s = student(sid)
    st = stats(sid)
    rate = s["rate"] or 0
    if st["left"] > 1:
        body = "Осталось {} оплаченных {}.".format(st["left"], plural(st["left"]))
    elif st["left"] == 1:
        body = "Осталось одно оплаченное занятие — напомню про оплату следующего пакета 🙂"
    elif st["left"] == 0:
        body = "Оплаченные занятия закончились. Подскажите, какой пакет берём дальше?"
    else:
        need = -st["left"]
        body = "Провели {} {} сверх оплаты.".format(need, plural(need))
        if rate:
            body += " К оплате: {}.".format(fmt_money(need * rate))
    options = ""
    if rate:
        options = "\n\nПакеты: 1 зан. — {}, 4 зан. — {}, 8 зан. — {}".format(
            fmt_money(rate), fmt_money(rate * 4), fmt_money(rate * 8))
    return "💳 <b>{}</b>\n\n{}{}".format(esc(s["name"]), body, options)


def text_schedule(sid):
    s = student(sid)
    nxt = next_dates(sid, max(stats(sid)["left"], 4))
    if not nxt:
        return "Расписание для {} пока не задано.".format(esc(s["name"]))
    lines = ["🗓 <b>Расписание — {}</b>".format(esc(s["name"])), ""]
    for d, t in nxt[:10]:
        lines.append("• {} {} {}".format(WEEKDAYS[d.weekday()], fmt_date(d, True), t).rstrip())
    return "\n".join(lines)


def screen_share(sid):
    rows = [[("📄 Выписка", "sh_st:%d" % sid)],
            [("💳 Напоминание об оплате", "sh_pay:%d" % sid)],
            [("🗓 Расписание", "sh_sch:%d" % sid)],
            [("⬅️ Назад", "st:%d" % sid)]]
    return ("📤 <b>Сообщение для ученика</b>\nБот пришлёт его отдельным сообщением — "
            "останется переслать ученику.", rows)


# ----------------------------------------------------------------------- Экспорт

def export_csv(chat_id):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Ученик", "Тип", "Дата", "Занятий", "Сумма", "Комментарий"])
    for s in students(chat_id) + list(students(chat_id, archived=True)):
        for l in q("SELECT * FROM lessons WHERE student_id=? ORDER BY held_on", (s["id"],)):
            kind = "занятие" if l["kind"] == "held" else (
                "отмена (списано)" if l["charged"] else "отмена (без списания)")
            w.writerow([s["name"], kind, fmt_date(l["held_on"]), l["charged"], "", l["note"] or ""])
        for p in q("SELECT * FROM payments WHERE student_id=? ORDER BY paid_on", (s["id"],)):
            w.writerow([s["name"], "оплата", fmt_date(p["paid_on"]), p["lessons"],
                        "{:.0f}".format(p["amount"] or 0), p["note"] or ""])
    send_document(chat_id, "tutor_{}.csv".format(today().isoformat()), buf.getvalue(),
                  caption="Выгрузка на " + fmt_date(today()))


# --------------------------------------------------------------------- Callback'и

def handle_callback(chat_id, message_id, cq_id, payload):
    tg("answerCallbackQuery", callback_query_id=cq_id)
    parts = payload.split(":")
    cmd = parts[0]
    sid = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else None

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
        lid = run("INSERT INTO lessons (student_id, held_on, kind, charged) VALUES (?,?,'held',1)",
                  (sid, today().isoformat()))
        t, r = screen_student(sid)
        r = [[("✍️ Добавить тему", "note:%d:%d" % (sid, lid))]] + r
        return edit(chat_id, message_id, "✅ Занятие {} записано\n\n".format(fmt_date(today())) + t, r)

    if cmd == "doned":
        set_state(chat_id, student_id=sid, pending={"action": "lesson_date", "sid": sid})
        return edit(chat_id, message_id, "Какой датой записать занятие?\nНапример: 15.09 или вчера",
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "note":
        lid = int(parts[2])
        set_state(chat_id, student_id=sid, pending={"action": "note", "sid": sid, "lid": lid})
        return edit(chat_id, message_id, "Что прошли на занятии? (тема, ДЗ)",
                    [[("⬅️ Пропустить", "st:%d" % sid)]])

    if cmd == "cancel":
        rows = [[("Списать занятие", "canc1:%d" % sid)],
                [("Без списания", "canc0:%d" % sid)],
                [("⬅️ Назад", "st:%d" % sid)]]
        return edit(chat_id, message_id,
                    "🚫 Отмена занятия сегодня.\nСписывать его с пакета?", rows)

    if cmd in ("canc1", "canc0"):
        charged = 1 if cmd == "canc1" else 0
        run("INSERT INTO lessons (student_id, held_on, kind, charged) VALUES (?,?,'cancel',?)",
            (sid, today().isoformat(), charged))
        t, r = screen_student(sid)
        return edit(chat_id, message_id, "🚫 Отмена записана\n\n" + t, r)

    if cmd == "undo":
        last = q("SELECT * FROM lessons WHERE student_id=? ORDER BY id DESC LIMIT 1", (sid,), one=True)
        if last:
            run("DELETE FROM lessons WHERE id=?", (last["id"],))
            head = "↩️ Запись от {} удалена\n\n".format(fmt_date(last["held_on"]))
        else:
            head = "Записей нет\n\n"
        t, r = screen_student(sid)
        return edit(chat_id, message_id, head + t, r)

    if cmd == "undopay":
        last = q("SELECT * FROM payments WHERE student_id=? ORDER BY id DESC LIMIT 1", (sid,), one=True)
        if last:
            run("DELETE FROM payments WHERE id=?", (last["id"],))
            head = "↩️ Оплата {} удалена\n\n".format(fmt_money(last["amount"]))
        else:
            head = "Оплат нет\n\n"
        t, r = screen_student(sid)
        return edit(chat_id, message_id, head + t, r)

    if cmd == "pay":
        return show(screen_pay, sid)

    if cmd == "payn":
        n = int(parts[2])
        s = student(sid)
        if s["rate"]:
            d = today()
            run("INSERT INTO payments (student_id, lessons, amount, paid_on) VALUES (?,?,?,?)",
                (sid, n, n * s["rate"], d.isoformat()))
            t, r = screen_student(sid)
            return edit(chat_id, message_id, "💰 Записано: {} зан. · {} · {}\n\n".format(
                n, fmt_money(n * s["rate"]), fmt_date(d)) + t, r)
        set_state(chat_id, student_id=sid, pending={"action": "amount", "sid": sid, "lessons": n})
        return edit(chat_id, message_id,
                    "Пакет {} зан.\nНапишите сумму (например 4000), можно с датой: 4000 12.09.\n"
                    "Без суммы — «-».".format(n), [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "payc":
        set_state(chat_id, student_id=sid, pending={"action": "custom_lessons", "sid": sid})
        return edit(chat_id, message_id, "Сколько занятий в пакете? Напишите число.",
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "sched":
        set_state(chat_id, student_id=sid, pending={"action": "schedule", "sid": sid})
        cur = slots_text(sid)
        return edit(chat_id, message_id,
                    "🗓 <b>Расписание</b>{}\n\nНапишите дни и время:\n<code>пн 17:00, чт 18:30</code>\n"
                    "Очистить — «-».".format("\nСейчас: " + cur if cur else ""),
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "hist":
        return show(screen_history, sid)

    if cmd == "share":
        return show(screen_share, sid)

    if cmd == "sh_st":
        send(chat_id, text_statement(sid))
        return
    if cmd == "sh_pay":
        send(chat_id, text_reminder(sid))
        return
    if cmd == "sh_sch":
        send(chat_id, text_schedule(sid))
        return

    if cmd == "more":
        rows = [[("💵 Ставка за занятие", "rate:%d" % sid)],
                [("✏️ Переименовать", "ren:%d" % sid)],
                [("↩️ Убрать последнее занятие", "undo:%d" % sid)],
                [("↩️ Убрать последнюю оплату", "undopay:%d" % sid)],
                [("🗄 В архив", "arch:%d" % sid)],
                [("⬅️ Назад", "st:%d" % sid)]]
        return edit(chat_id, message_id, "⚙️ <b>{}</b>".format(esc(student(sid)["name"])), rows)

    if cmd == "rate":
        set_state(chat_id, student_id=sid, pending={"action": "rate", "sid": sid})
        return edit(chat_id, message_id, "Сколько стоит одно занятие? Напишите число.",
                    [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "ren":
        set_state(chat_id, student_id=sid, pending={"action": "rename", "sid": sid})
        return edit(chat_id, message_id, "Новое имя ученика?", [[("⬅️ Назад", "st:%d" % sid)]])

    if cmd == "arch":
        run("UPDATE students SET archived=1 WHERE id=?", (sid,))
        t, r = screen_students(chat_id)
        return edit(chat_id, message_id, "🗄 Ученик в архиве (данные сохранены)\n\n" + t, r)

    if cmd == "unarch":
        run("UPDATE students SET archived=0 WHERE id=?", (sid,))
        return show(screen_student, sid)


# ------------------------------------------------------------------ Ввод текстом

def handle_pending(chat_id, pending, text):
    action = pending.get("action")
    sid = pending.get("sid")

    if action == "new_student":
        name = text.strip()[:60]
        new_id = run("INSERT INTO students (chat_id, name) VALUES (?,?)", (chat_id, name))
        set_state(chat_id, student_id=new_id, pending=None)
        t, r = screen_student(new_id)
        return send(chat_id, "➕ Ученик добавлен\n\n" + t, r)

    if action == "rename":
        run("UPDATE students SET name=? WHERE id=?", (text.strip()[:60], sid))
        set_state(chat_id, pending=None)
        t, r = screen_student(sid)
        return send(chat_id, t, r)

    if action == "rate":
        digits = re.sub(r"[^\d.,]", "", text).replace(",", ".")
        if not digits.strip("."):
            return send(chat_id, "Нужно число, например 2500.")
        run("UPDATE students SET rate=? WHERE id=?", (float(digits), sid))
        set_state(chat_id, pending=None)
        t, r = screen_student(sid)
        return send(chat_id, "💵 Ставка сохранена\n\n" + t, r)

    if action == "note":
        run("UPDATE lessons SET note=? WHERE id=?", (text.strip()[:200], pending["lid"]))
        set_state(chat_id, pending=None)
        t, r = screen_student(sid)
        return send(chat_id, "✍️ Тема записана\n\n" + t, r)

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
            t, r = screen_student(sid)
            return send(chat_id, "💰 Записано: {} зан. · {}\n\n".format(
                n, fmt_money(n * s["rate"])) + t, r)
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
        t, r = screen_student(sid)
        return send(chat_id, "💰 Записано: {} зан. · {} · {}\n\n".format(
            n, fmt_money(amount), fmt_date(d)) + t, r)

    if action == "lesson_date":
        d = parse_date(text)
        if not d:
            return send(chat_id, "Не поняла дату. Например: 15.09, 15.09.2026, вчера.")
        lid = run("INSERT INTO lessons (student_id, held_on, kind, charged) VALUES (?,?,'held',1)",
                  (sid, d.isoformat()))
        set_state(chat_id, pending=None)
        t, r = screen_student(sid)
        r = [[("✍️ Добавить тему", "note:%d:%d" % (sid, lid))]] + r
        return send(chat_id, "✅ Занятие {} записано\n\n".format(fmt_date(d)) + t, r)

    if action == "schedule":
        run("DELETE FROM slots WHERE student_id=?", (sid,))
        if text.strip() not in ("-", "—"):
            slots = parse_slots(text)
            if not slots:
                return send(chat_id, "Не поняла. Формат: пн 17:00, чт 18:30")
            for wd, at in slots:
                run("INSERT INTO slots (student_id, weekday, at) VALUES (?,?,?)", (sid, wd, at))
        set_state(chat_id, pending=None)
        t, r = screen_student(sid)
        return send(chat_id, "🗓 Расписание обновлено\n\n" + t, r)

    set_state(chat_id, pending=None)
    return send(chat_id, HELP)


# -------------------------------------------------------------------- Команды

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

    if cmd == "export":
        return export_csv(chat_id)

    sid = st["student_id"]
    if cmd in ("done", "занятие") and sid:
        d = parse_date(arg) if arg else today()
        if not d:
            return send(chat_id, "Не поняла дату.")
        lid = run("INSERT INTO lessons (student_id, held_on, kind, charged) VALUES (?,?,'held',1)",
                  (sid, d.isoformat()))
        t, r = screen_student(sid)
        r = [[("✍️ Добавить тему", "note:%d:%d" % (sid, lid))]] + r
        return send(chat_id, "✅ Занятие {} записано\n\n".format(fmt_date(d)) + t, r)

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


# ------------------------------------------------------------------- Дайджест

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
            for d, t in next_dates(s["id"], 3):
                if d != today():
                    break
                st = stats(s["id"])
                items.append("• {} {}{}".format(
                    t or "", esc(s["name"]),
                    " ⚠️ оплата закончилась" if st["left"] <= 0 else ""))
        if items:
            send(chat_id, "☀️ <b>Сегодня занятия</b>\n" + "\n".join(items))


# ------------------------------------------------------------------ Диспетчер

def allowed(user_id):
    return OWNER_ID == 0 or user_id == OWNER_ID


def handle(update):
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg.get("from", {}).get("id")
        text = msg.get("text") or ""
        if not text.strip():
            return
        if not allowed(user_id):
            if text.startswith("/id"):
                return send(chat_id, "Ваш Telegram ID: <code>{}</code>".format(user_id))
            return send(chat_id, "Это личный бот преподавателя 🙂")
        if text.startswith("/"):
            return handle_command(chat_id, user_id, text)
        pending = get_state(chat_id)["pending"]
        if pending:
            return handle_pending(chat_id, pending, text)
        t, r = screen_students(chat_id)
        return send(chat_id, t, r)

    if "callback_query" in update:
        cq = update["callback_query"]
        user_id = cq["from"]["id"]
        msg = cq.get("message") or {}
        chat_id = msg.get("chat", {}).get("id")
        if not chat_id:
            return
        if not allowed(user_id):
            return tg("answerCallbackQuery", callback_query_id=cq["id"],
                      text="Это личный бот преподавателя")
        return handle_callback(chat_id, msg["message_id"], cq["id"], cq.get("data") or "")


def main():
    if not TOKEN:
        raise SystemExit("Задайте токен: export TG_BOT_TOKEN='...'")
    db().close()
    me = tg("getMe").get("result", {})
    print("Бот запущен: @" + str(me.get("username")))
    tg("setMyCommands", commands=[
        {"command": "students", "description": "Список учеников"},
        {"command": "month", "description": "Итоги месяца"},
        {"command": "week", "description": "Расписание на неделю"},
        {"command": "export", "description": "Выгрузка в CSV"},
        {"command": "help", "description": "Справка"},
    ])
    offset = None
    while True:
        res = tg("getUpdates", offset=offset, timeout=30, allowed_updates=["message", "callback_query"])
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
