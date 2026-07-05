import os
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Almaty")
TOKEN = os.environ.get("BOT_TOKEN", "")
DATA_FILE = "data.json"

# ─── DATA ────────────────────────────────────────────────────────────────────

def load():
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except:
        return {"days": {}, "cal": {}, "prog": {}, "hab": {}}

def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def today_key():
    return datetime.now(TZ).strftime("%Y-%m-%d")

def tomorrow_key():
    return (datetime.now(TZ) + timedelta(days=1)).strftime("%Y-%m-%d")

def day_name(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    names = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]
    months = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"]
    return f"{names[d.weekday()]}, {d.day} {months[d.month-1]}"

# ─── BLOCKS ──────────────────────────────────────────────────────────────────

BASE = [
    ("wake",   "10:30", "Подъём",           "20 мин без телефона — вода, умыться"),
    ("bfast",  "10:50", "Завтрак + сборы",  "40 мин"),
    ("go",     "11:30", "Выезд в офис",     "До часа пик"),
    ("solf",   "12:00", "Сольфеджио",       "20–30 мин"),
    ("b1",     "12:30", "Перерыв",          "10 мин"),
    ("piano",  "12:40", "Фортепиано",       "45 мин — гаммы, этюд"),
    ("b2",     "13:25", "Перерыв",          "10 мин"),
    ("flute",  "13:35", "Флейта",           "30 мин — долгие ноты, гаммы"),
    ("b3",     "14:05", "Перерыв",          "10 мин"),
    ("ear",    "14:15", "Ear Training",     "20 мин"),
    ("lunch",  "14:35", "Обед + пауза",     "45 мин"),
    ("mix",    "15:20", "Микс / Pro Tools", "2 ч"),
    ("work",   "17:20", "Работа / прокат",  "1.5–2 ч"),
    ("free",   "19:00", "Свободное время",  "Отдых"),
    ("rev",    "22:30", "Ревью дня",        "5 мин — записать в заметки"),
    ("slp",    "23:30", "Отбой",            "Цель — до полуночи"),
]

ORCH = [
    ("wake",  "7:50",  "Подъём",           "Ранний — вода, одеться"),
    ("go1",   "8:30",  "Выезд на оркестр", "Быть в 9:30"),
    ("orch",  "9:30",  "Оркестр",          "До ~12:00"),
    ("go2",   "12:00", "Выезд в офис",     "~30 мин"),
    ("lunch", "12:30", "Обед",             "30 мин"),
    ("solf",  "13:00", "Сольфеджио",       "20–30 мин"),
    ("piano", "13:30", "Фортепиано",       "30 мин"),
    ("ear",   "14:00", "Ear Training",     "20 мин"),
    ("mix",   "14:20", "Микс / Pro Tools", "1.5 ч"),
    ("free",  "16:00", "Свободное время",  ""),
    ("rev",   "22:30", "Ревью дня",        "5 мин"),
    ("slp",   "23:30", "Отбой",            ""),
]

LIVE = [
    ("wake",  "10:30", "Подъём",           "20 мин без телефона"),
    ("bfast", "10:50", "Завтрак + сборы",  ""),
    ("piano", "11:30", "Фортепиано",       "Минимум 20 мин — не отменяется"),
    ("solf",  "12:00", "Сольфеджио",       "20 мин"),
    ("mix",   "12:20", "Микс / теория",    "Сколько есть"),
    ("live",  "—",     "Лайв",             "Выезд → работа → возврат"),
    ("rev",   "После", "Ревью дня",        "5 мин даже если ночь"),
]

def get_blocks(date_str, data):
    evts = data.get("cal", {}).get(date_str, [])
    bl = list(BASE)
    if any(e.get("type") == "orch" for e in evts):
        bl = list(ORCH)
    elif any(e.get("type") == "live" for e in evts):
        bl = list(LIVE)
    # Вставляем события с временем как блоки
    for e in evts:
        if e.get("type") in ("busy", "personal"):
            import re
            m = re.search(r"(\d{1,2}:\d{2})", e.get("text", ""))
            if m:
                eid = "evt_" + e["text"][:15].replace(" ", "_").lower()
                name = re.sub(r"\s*\d{1,2}:\d{2}", "", e["text"]).strip()
                new_bl = (eid, m.group(1), name, "")
                if not any(b[0] == eid for b in bl):
                    rev_idx = next((i for i, b in enumerate(bl) if b[0] == "rev"), len(bl))
                    bl.insert(rev_idx, new_bl)
    return bl

# ─── PHASES ──────────────────────────────────────────────────────────────────

PHASES = [
    {"id":"sl1","cat":"Сольфеджио","w":"1–4","title":"Ноты и ритм","tasks":["Читать ноты в скрипичном ключе","Ритм: четверть/восьмая/половинная","Петь мелодию по нотам"],"res":"musictheory.net/lessons"},
    {"id":"sl2","cat":"Сольфеджио","w":"5–10","title":"Интервалы и пение","tasks":["Петь гамму До мажор","Диктант на слух","Интонировать интервалы"],"req":"sl1"},
    {"id":"sl3","cat":"Сольфеджио","w":"11–20","title":"Тональности","tasks":["Знаки при ключе до 3 диезов","Хроматическая гамма","Транспозиция мелодии"],"req":"sl2"},
    {"id":"et1","cat":"Ear Training","w":"1–4","title":"Интервалы","tasks":["musictheory.net/exercises/ear-interval","Ассоциации: терция=Подмосковные вечера","Различать приму/терцию/квинту/октаву"],"req":"sl1","res":"musictheory.net/exercises/ear-interval"},
    {"id":"et2","cat":"Ear Training","w":"5–8","title":"Аккорды и лады","tasks":["musictheory.net/exercises/ear-chord","Мажор/минор/доминант-септ","Анализ трека — найти тональность"],"req":"et1"},
    {"id":"et3","cat":"Ear Training","w":"9–16","title":"Тембр и частоты","tasks":["quiztones.com — угадывать частоты","100Гц=бум / 1–3кГц=присутствие","Слышать компрессию без плагина"],"req":"et2"},
    {"id":"pn1","cat":"Фортепиано","w":"1–4","title":"Постановка рук","tasks":["Разогрев 5 мин","До-Ре-Ми-Фа-Соль каждой рукой","imslp.org — Бах Менуэт BWV Anh.114"],"req":"sl1"},
    {"id":"pn2","cat":"Фортепиано","w":"5–10","title":"Гаммы + аккорды","tasks":["Гамма До мажор двумя руками 60bpm","Трезвучия До–Фа–Соль","По 4 такта с метрономом"],"req":"pn1"},
    {"id":"pn3","cat":"Фортепиано","w":"11–20","title":"Джаз","tasks":["Гаммы Соль и Ре мажор","Cmaj7/Dm7/G7 — аппликатура","musicnotes.com — Autumn Leaves"],"req":"pn2"},
    {"id":"fl1","cat":"Флейта","w":"1–2","title":"Возобновление","tasks":["Долгие ноты Ля/Си/До — один вдох","Гамма До мажор одна октава","Простая мелодия + запись на телефон"],"req":"sl1"},
    {"id":"fl2","cat":"Флейта","w":"3–8","title":"Техника","tasks":["Долгие ноты хроматически","Гаммы двух октав + арпеджио","imslp.org — Андерсен op.33"],"req":"fl1"},
    {"id":"mx1","cat":"Микс + PT","w":"1–3","title":"PT: среда + анализ","tasks":["Command+= Edit↔Mix, Smart Tool F6","Clip Gain vs Input Gain","Референс в PT — EQ3, 3 наблюдения"]},
    {"id":"mx2","cat":"Микс + PT","w":"4–6","title":"PT: сессия + баланс","tasks":["Dante I/O + шаблон .ptx","Баланс без плагинов — фейдеры и пан","HPF: вокал 80–100 Гц / гитара 100–120"],"req":"mx1"},
    {"id":"mx3","cat":"Микс + PT","w":"7–10","title":"Плотность и динамика","tasks":["Dyn3 на кике: ratio 4:1, attack 10мс","Параллельная компрессия на Aux","Сатурация + тест на телефоне"],"req":"mx2"},
    {"id":"mx4","cat":"Микс + PT","w":"11+","title":"Реальные проекты","tasks":["Протокол 8 шагов на каждый проект","Logic vs PT — сравнение workflow"],"req":"mx3"},
]

def is_unlocked(ph, prog):
    req = ph.get("req")
    if not req:
        return True
    r = next((p for p in PHASES if p["id"] == req), None)
    if not r:
        return True
    return all(prog.get(f"{r['id']}_{i}") for i in range(len(r["tasks"])))

# ─── KEYBOARDS ───────────────────────────────────────────────────────────────

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Сегодня", callback_data="today"),
         InlineKeyboardButton("📅 Завтра", callback_data="tomorrow")],
        [InlineKeyboardButton("🗓 Календарь", callback_data="cal_menu"),
         InlineKeyboardButton("📖 Методичка", callback_data="method")],
        [InlineKeyboardButton("🔥 Привычки", callback_data="habits"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats")],
    ])

def back_kb(to="menu"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data=to)]])

# ─── RENDERERS ───────────────────────────────────────────────────────────────

def render_day(date_str, data):
    evts = data.get("cal", {}).get(date_str, [])
    blocks = get_blocks(date_str, data)
    checked = data.get("days", {}).get(date_str, {}).get("checked", {})
    done = sum(1 for b in blocks if checked.get(b[0]))
    pct = round(done / len(blocks) * 100) if blocks else 0

    lines = [f"*{day_name(date_str)}*"]

    evt_icons = {"orch": "🎼", "live": "🎤", "busy": "📌", "personal": "👤"}
    for e in evts:
        icon = evt_icons.get(e.get("type"), "•")
        lines.append(f"{icon} {e.get('text', '')}")

    lines.append(f"\n▓ Прогресс: {done}/{len(blocks)} блоков — {pct}%")
    lines.append("─" * 25)

    kb_rows = []
    for b in blocks:
        bid, time, name, desc = b
        ck = checked.get(bid, False)
        mark = "✅" if ck else "⬜"
        label = f"{mark} {time} {name}"
        if desc:
            label += f" — {desc}"
        kb_rows.append([InlineKeyboardButton(label, callback_data=f"tog_{date_str}_{bid}")])

    kb_rows.append([InlineKeyboardButton("➕ Добавить событие", callback_data=f"add_evt_{date_str}")])
    kb_rows.append([InlineKeyboardButton("← Меню", callback_data="menu")])

    return "\n".join(lines), InlineKeyboardMarkup(kb_rows)

def render_method(data):
    prog = data.get("prog", {})
    cats = []
    seen = []
    for ph in PHASES:
        if ph["cat"] not in seen:
            seen.append(ph["cat"])
            cats.append(ph["cat"])

    text = "*📖 Методичка*\n\nНажми на фазу чтобы открыть задачи:\n"
    kb_rows = []
    for cat in cats:
        kb_rows.append([InlineKeyboardButton(f"── {cat} ──", callback_data="noop")])
        for ph in PHASES:
            if ph["cat"] != cat:
                continue
            unlocked = is_unlocked(ph, prog)
            tot = len(ph["tasks"])
            dn = sum(1 for i in range(tot) if prog.get(f"{ph['id']}_{i}"))
            pct = round(dn / tot * 100) if tot else 0
            lock = "" if unlocked else "🔒 "
            bar = "█" * (pct // 20) + "░" * (5 - pct // 20)
            label = f"{lock}{ph['title']} [{ph['w']} нед.] {bar} {dn}/{tot}"
            kb_rows.append([InlineKeyboardButton(label, callback_data=f"phase_{ph['id']}")])

    kb_rows.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return text, InlineKeyboardMarkup(kb_rows)

def render_phase(ph_id, data):
    prog = data.get("prog", {})
    ph = next((p for p in PHASES if p["id"] == ph_id), None)
    if not ph:
        return "Фаза не найдена", back_kb("method")

    unlocked = is_unlocked(ph, prog)
    lines = [f"*{ph['cat']} — {ph['title']}*", f"Недели: {ph['w']}"]
    if not unlocked:
        req_id = ph.get("req")
        req = next((p for p in PHASES if p["id"] == req_id), None)
        lines.append(f"\n🔒 Заблокировано. Сначала завершите: {req['title'] if req else req_id}")
        return "\n".join(lines), back_kb("method")

    if ph.get("res"):
        lines.append(f"📎 {ph['res']}")

    lines.append("\n*Задачи:*")
    kb_rows = []
    for i, task in enumerate(ph["tasks"]):
        done = prog.get(f"{ph_id}_{i}", False)
        mark = "✅" if done else "⬜"
        kb_rows.append([InlineKeyboardButton(f"{mark} {task}", callback_data=f"tog_prog_{ph_id}_{i}")])

    kb_rows.append([InlineKeyboardButton("← Методичка", callback_data="method")])
    return "\n".join(lines), InlineKeyboardMarkup(kb_rows)

def render_habits(data, week_offset=0):
    hab = data.get("hab", {})
    now = datetime.now(TZ)
    dow = now.weekday()
    monday = now - timedelta(days=dow) + timedelta(weeks=week_offset)
    dates = [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    dn = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    cats = [("piano","🔵 Фортепиано"),("flute","🔵 Флейта"),("mix","🔵 Микс/учёба"),("review","🔴 Ревью")]

    f_date = datetime.strptime(dates[0], "%Y-%m-%d")
    l_date = datetime.strptime(dates[6], "%Y-%m-%d")
    months = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]
    text = f"*🔥 Привычки*\n{f_date.day} {months[f_date.month-1]} – {l_date.day} {months[l_date.month-1]}\n"

    kb_rows = []
    # Шапка с датами
    header = " ".join(f"{dn[i]}\n{datetime.strptime(d,'%Y-%m-%d').day}" for i, d in enumerate(dates))

    for cat, lbl in cats:
        row = []
        for i, d in enumerate(dates):
            on = hab.get(f"{d}_{cat}", False)
            mark = "✅" if on else "⬜"
            row.append(InlineKeyboardButton(f"{mark}", callback_data=f"tog_hab_{d}_{cat}"))
        kb_rows.append([InlineKeyboardButton(lbl, callback_data="noop")])
        kb_rows.append(row)

    nav = [
        InlineKeyboardButton("◀", callback_data=f"habits_{week_offset-1}"),
        InlineKeyboardButton("▶", callback_data=f"habits_{week_offset+1}"),
    ]
    kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return text, InlineKeyboardMarkup(kb_rows)

def render_stats(data):
    hab = data.get("hab", {})
    prog = data.get("prog", {})

    piano = sum(1 for k, v in hab.items() if k.endswith("_piano") and v)
    flute = sum(1 for k, v in hab.items() if k.endswith("_flute") and v)
    mix = sum(1 for k, v in hab.items() if k.endswith("_mix") and v)
    review = sum(1 for k, v in hab.items() if k.endswith("_review") and v)

    # Streak
    streak = 0
    tk = today_key()
    for i in range(365):
        d = (datetime.now(TZ) - timedelta(days=i)).strftime("%Y-%m-%d")
        if hab.get(f"{d}_review") or hab.get(f"{d}_piano") or hab.get(f"{d}_mix"):
            streak += 1
        elif d != tk:
            break

    ph_done = sum(1 for ph in PHASES if all(prog.get(f"{ph['id']}_{i}") for i in range(len(ph["tasks"]))))

    text = (
        f"*📊 Статистика*\n\n"
        f"🔥 Дней подряд: *{streak}*\n\n"
        f"🔵 Сессий фортепиано: *{piano}*\n"
        f"🔵 Сессий флейта: *{flute}*\n"
        f"🔵 Сессий учёбы: *{mix}*\n"
        f"🔴 Ревью дней: *{review}*\n\n"
        f"📖 Фаз пройдено: *{ph_done}/{len(PHASES)}*"
    )
    return text, back_kb("menu")

def render_cal_menu(data):
    now = datetime.now(TZ)
    text = "*🗓 Календарь*\n\nВыбери день:"
    kb_rows = []
    row = []
    for i in range(7):
        d = (now + timedelta(days=i))
        ds = d.strftime("%Y-%m-%d")
        evts = data.get("cal", {}).get(ds, [])
        checked = data.get("days", {}).get(ds, {}).get("checked", {})
        blocks = get_blocks(ds, data)
        done = sum(1 for b in blocks if checked.get(b[0]))
        pct = round(done / len(blocks) * 100) if blocks else 0
        dot = "🟢" if pct == 100 else ("🟡" if pct > 0 else ("🔴" if evts else "⬜"))
        label = f"{dot} {d.day}"
        row.append(InlineKeyboardButton(label, callback_data=f"cal_day_{ds}"))
        if len(row) == 4:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    kb_rows.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return text, InlineKeyboardMarkup(kb_rows)

# ─── HANDLERS ────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = "👋 Привет, Марк!\n\nТвой персональный планировщик. Выбери раздел:"
    await update.message.reply_text(text, reply_markup=main_menu_kb(), parse_mode="Markdown")

async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = load()
    d = q.data

    if d == "menu":
        await q.edit_message_text("Выбери раздел:", reply_markup=main_menu_kb())

    elif d == "today":
        text, kb = render_day(today_key(), data)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d == "tomorrow":
        text, kb = render_day(tomorrow_key(), data)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d.startswith("cal_day_"):
        ds = d[8:]
        text, kb = render_day(ds, data)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d == "cal_menu":
        text, kb = render_cal_menu(data)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d == "method":
        text, kb = render_method(data)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d.startswith("phase_"):
        ph_id = d[6:]
        text, kb = render_phase(ph_id, data)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d == "habits":
        text, kb = render_habits(data, 0)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d.startswith("habits_"):
        off = int(d[7:])
        text, kb = render_habits(data, off)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d == "stats":
        text, kb = render_stats(data)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d.startswith("tog_"):
        parts = d.split("_", 2)
        # tog_{date}_{block_id} или tog_prog_{ph_id}_{i} или tog_hab_{date}_{cat}
        if parts[1] == "prog":
            _, _, ph_id, idx = d.split("_", 3)
            key = f"{ph_id}_{idx}"
            if "prog" not in data:
                data["prog"] = {}
            data["prog"][key] = not data["prog"].get(key, False)
            save(data)
            text, kb = render_phase(ph_id, data)
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

        elif parts[1] == "hab":
            _, _, date_str, cat = d.split("_", 3)
            if "hab" not in data:
                data["hab"] = {}
            key = f"{date_str}_{cat}"
            data["hab"][key] = not data["hab"].get(key, False)
            save(data)
            # Определяем текущий offset
            now = datetime.now(TZ)
            d_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ)
            diff = (d_dt - now).days
            off = diff // 7
            text, kb = render_habits(data, off)
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

        else:
            # tog_{date}_{block_id}
            rest = d[4:]
            date_str = rest[:10]
            bid = rest[11:]
            if "days" not in data:
                data["days"] = {}
            if date_str not in data["days"]:
                data["days"][date_str] = {"checked": {}}
            checked = data["days"][date_str].get("checked", {})
            checked[bid] = not checked.get(bid, False)
            data["days"][date_str]["checked"] = checked
            # Синхронизируем привычки
            if checked[bid]:
                if "hab" not in data:
                    data["hab"] = {}
                if bid == "piano":
                    data["hab"][f"{date_str}_piano"] = True
                elif bid == "flute":
                    data["hab"][f"{date_str}_flute"] = True
                elif bid in ("mix", "ear", "solf"):
                    data["hab"][f"{date_str}_mix"] = True
                elif bid == "rev":
                    data["hab"][f"{date_str}_review"] = True
            save(data)
            text, kb = render_day(date_str, data)
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d.startswith("add_evt_"):
        date_str = d[8:]
        ctx.user_data["add_evt_date"] = date_str
        ctx.user_data["add_evt_step"] = "type"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎼 Оркестр", callback_data=f"evt_type_orch_{date_str}"),
             InlineKeyboardButton("🎤 Лайв", callback_data=f"evt_type_live_{date_str}")],
            [InlineKeyboardButton("📌 Дела", callback_data=f"evt_type_busy_{date_str}"),
             InlineKeyboardButton("👤 Личное", callback_data=f"evt_type_personal_{date_str}")],
            [InlineKeyboardButton("← Назад", callback_data=f"cal_day_{date_str}")],
        ])
        await q.edit_message_text("Выбери тип события:", reply_markup=kb)

    elif d.startswith("evt_type_"):
        parts = d.split("_")
        evt_type = parts[2]
        date_str = "_".join(parts[3:])
        ctx.user_data["add_evt_date"] = date_str
        ctx.user_data["add_evt_type"] = evt_type
        await q.edit_message_text(f"Введи описание события для {date_str}:\n(например: 'Оркестр 9:30')")

    elif d == "noop":
        pass

async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.user_data.get("add_evt_date") and ctx.user_data.get("add_evt_type"):
        date_str = ctx.user_data.pop("add_evt_date")
        evt_type = ctx.user_data.pop("add_evt_type")
        text = update.message.text
        data = load()
        if "cal" not in data:
            data["cal"] = {}
        if date_str not in data["cal"]:
            data["cal"][date_str] = []
        data["cal"][date_str].append({"type": evt_type, "text": text})
        save(data)
        t, kb = render_day(date_str, data)
        await update.message.reply_text(f"✅ Событие добавлено!", parse_mode="Markdown")
        await update.message.reply_text(t, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text("Используй /start для меню")

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
