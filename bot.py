import os, json, logging, re
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters, JobQueue
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Almaty")
TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
DATA_FILE = "data.json"

# ─── DATA ────────────────────────────────────────────────────────────────────

def load():
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except:
        return {"days": {}, "cal": {}, "prog": {}, "hab": {}, "custom_blocks": {}}

def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def now_almaty():
    return datetime.now(TZ)

def today_key():
    return now_almaty().strftime("%Y-%m-%d")

def tomorrow_key():
    return (now_almaty() + timedelta(days=1)).strftime("%Y-%m-%d")

def day_name(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    names = ["Понедельник","Вторник","Среда","Четверг","Пятница","Суббота","Воскресенье"]
    months = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"]
    return f"{names[d.weekday()]}, {d.day} {months[d.month-1]}"

def time_to_min(t_str):
    try:
        h, m = t_str.split(":")
        return int(h) * 60 + int(m)
    except:
        return 9999

def min_to_time(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"

# ─── BASE SCHEDULE ───────────────────────────────────────────────────────────

DEFAULT_BLOCKS = [
    {"id": "wake",   "t": "07:30", "n": "Подъём",           "d": "Без телефона — вода, умыться, выглянуть в окно", "dur": 20},
    {"id": "bfast",  "t": "07:50", "n": "Завтрак + сборы",  "d": "40 мин", "dur": 40},
    {"id": "go",     "t": "08:30", "n": "Выезд в офис",     "d": "До часа пик", "dur": 60},
    {"id": "solf",   "t": "09:30", "n": "Сольфеджио",       "d": "20–30 мин", "dur": 30},
    {"id": "b1",     "t": "10:00", "n": "Перерыв",          "d": "10 мин", "dur": 10},
    {"id": "piano",  "t": "10:10", "n": "Фортепиано",       "d": "45 мин — гаммы, этюд", "dur": 45},
    {"id": "b2",     "t": "10:55", "n": "Перерыв",          "d": "10 мин", "dur": 10},
    {"id": "flute",  "t": "11:05", "n": "Флейта",           "d": "30 мин — долгие ноты, гаммы", "dur": 30},
    {"id": "b3",     "t": "11:35", "n": "Перерыв",          "d": "10 мин", "dur": 10},
    {"id": "ear",    "t": "11:45", "n": "Ear Training",     "d": "20 мин", "dur": 20},
    {"id": "lunch",  "t": "12:05", "n": "Обед + пауза",    "d": "45 мин — выйти из офиса", "dur": 45},
    {"id": "mix",    "t": "12:50", "n": "Микс / Pro Tools", "d": "2 ч", "dur": 120},
    {"id": "work",   "t": "14:50", "n": "Работа / прокат",  "d": "до вечера", "dur": 150},
    {"id": "free",   "t": "17:20", "n": "Свободное время",  "d": "Отдых", "dur": 130},
    {"id": "rev",    "t": "19:30", "n": "Ревью дня",        "d": "5 мин — записать в заметки", "dur": 10},
    {"id": "wind",   "t": "21:00", "n": "Подготовка ко сну","d": "Убрать телефон, приглушить свет", "dur": 60},
    {"id": "slp",    "t": "22:00", "n": "Отбой",            "d": "Цель — до 22:00", "dur": 0},
]

def get_blocks(date_str, data):
    custom = data.get("custom_blocks", {}).get(date_str)
    if custom:
        blocks = custom
    else:
        blocks = [b.copy() for b in DEFAULT_BLOCKS]

    evts = data.get("cal", {}).get(date_str, [])
    for e in evts:
        if e.get("type") in ("busy", "personal"):
            m = re.search(r"(\d{1,2}:\d{2})", e.get("text", ""))
            if m:
                eid = "evt_" + re.sub(r"\W", "_", e["text"])[:15].lower()
                name = re.sub(r"\s*\d{1,2}:\d{2}", "", e["text"]).strip() or e["text"]
                if not any(b["id"] == eid for b in blocks):
                    new_blk = {"id": eid, "t": m.group(1), "n": name, "d": "", "dur": 60}
                    blocks = insert_and_shift(blocks, new_blk)

    return sorted(blocks, key=lambda b: time_to_min(b["t"]))

def insert_and_shift(blocks, new_blk):
    new_min = time_to_min(new_blk["t"])
    result = []
    shifted = False
    current_min = new_min + new_blk.get("dur", 60)

    for b in sorted(blocks, key=lambda x: time_to_min(x["t"])):
        bmin = time_to_min(b["t"])
        if not shifted and bmin >= new_min:
            result.append(new_blk)
            shifted = True
        if shifted and bmin < current_min:
            b = b.copy()
            b["t"] = min_to_time(current_min)
            current_min += b.get("dur", 30)
        result.append(b)

    if not shifted:
        result.append(new_blk)
    return result

# ─── PHASES ──────────────────────────────────────────────────────────────────

PHASES = [
    {
        "id": "sl1", "cat": "🟣 Сольфеджио", "w": "1–4", "title": "Ноты и ритм",
        "tasks": [
            "Линейки скрипичного ключа: Ми-Соль-Си-Ре-Фа (Мама Гоши Сделала Рисовую Фигуру)",
            "Промежутки: Фа-Ля-До-Ми",
            "Ритм: целая=4, половинная=2, четверть=1, восьмая=0.5 — отстукивай по колену",
            "Петь мелодию по нотам с фортепиано и без",
        ],
        "links": [
            ("musictheory.net/lessons", "https://www.musictheory.net/lessons"),
            ("Тренажёр нот", "https://www.musictheory.net/exercises/note"),
        ]
    },
    {
        "id": "sl2", "cat": "🟣 Сольфеджио", "w": "5–10", "title": "Интервалы и пение",
        "req": "sl1",
        "tasks": [
            "Петь гамму До мажор по нотам с фортепиано и без",
            "Диктант — записать мелодию на слух: найди первую ноту, запиши, дальше по слуху",
            "Интонировать интервалы: терция, квинта, октава",
        ],
        "links": [
            ("Тренажёр нот", "https://www.musictheory.net/exercises/note"),
        ]
    },
    {
        "id": "sl3", "cat": "🟣 Сольфеджио", "w": "11–20", "title": "Тональности",
        "req": "sl2",
        "tasks": [
            "Знаки при ключе: диезы Фа-До-Соль-Ре-Ля-Ми-Си, бемоли обратно",
            "1 диез=Соль мажор, 2=Ре мажор, 3=Ля мажор",
            "Хроматическая гамма — петь и записывать",
            "Транспозиция мелодии в другую тональность",
        ],
        "links": []
    },
    {
        "id": "et1", "cat": "🟣 Ear Training", "w": "1–4", "title": "Интервалы",
        "req": "sl1",
        "tasks": [
            "Тренажёр интервалов на слух — 20 мин в день",
            "Ассоциации: малая терция=Подмосковные вечера, квинта=Star Wars, октава=Somewhere Over the Rainbow",
            "Различать приму/терцию/квинту/октаву уверенно",
            "Петь интервалы от любой ноты вверх и вниз",
        ],
        "links": [
            ("Ear interval тренажёр", "https://www.musictheory.net/exercises/ear-interval"),
        ]
    },
    {
        "id": "et2", "cat": "🟣 Ear Training", "w": "5–8", "title": "Аккорды и лады",
        "req": "et1",
        "tasks": [
            "Мажор=радостно, минор=грустно, G7=напряжённо — различать на слух",
            "10–15 аккордов за сессию, записывай % угадывания",
            "Анализ трека: мажор или минор? Где тоника? Первые 4 аккорда",
        ],
        "links": [
            ("Ear chord тренажёр", "https://www.musictheory.net/exercises/ear-chord"),
        ]
    },
    {
        "id": "et3", "cat": "🟣 Ear Training", "w": "9–16", "title": "Тембр и частоты",
        "req": "et2",
        "tasks": [
            "100 Гц=бум, 200–400=каша, 1–3 кГц=присутствие, 5–8 кГц=резкость",
            "Ugадывать поднятую/срезанную частоту — 30 мин в день",
            "Слышать компрессию без плагина: барабаны + ratio 10:1, bypass туда-сюда",
        ],
        "links": [
            ("Quiztones — частоты", "https://www.quiztones.com"),
        ]
    },
    {
        "id": "pn1", "cat": "🔵 Фортепиано", "w": "1–4", "title": "Постановка рук",
        "req": "sl1",
        "tasks": [
            "Разогрев 5 мин: сжимай пальцы от мизинца, вращай запястья по 10 раз",
            "До-Ре-Ми-Фа-Соль каждой рукой — большой на До (C4), медленно с весом",
            "Бах Менуэт BWV Anh.114: по 2 такта правая → левая → вместе",
            "Не переходи дальше пока эти 2 такта не звучат уверенно",
        ],
        "links": [
            ("Ноты Менуэта Баха (IMSLP)", "https://imslp.org/wiki/Minuet_in_G_major,_BWV_Anh.114_(Bach,_Johann_Sebastian)"),
        ]
    },
    {
        "id": "pn2", "cat": "🔵 Фортепиано", "w": "5–10", "title": "Гаммы + аккорды",
        "req": "pn1",
        "tasks": [
            "Гамма До мажор двумя руками 2 октавы, метроном 60 bpm — аппликатура 1-2-3/1-2-3-4-5",
            "Трезвучия До-Фа-Соль с левым басом",
            "Пьеса по 4 такта: правая → левая → вместе, метроном обязателен",
        ],
        "links": [
            ("Ноты Менуэта Баха (IMSLP)", "https://imslp.org/wiki/Minuet_in_G_major,_BWV_Anh.114_(Bach,_Johann_Sebastian)"),
        ]
    },
    {
        "id": "pn3", "cat": "🔵 Фортепиано", "w": "11–20", "title": "Джаз",
        "req": "pn2",
        "tasks": [
            "Гаммы Соль (Фа#) и Ре (Фа#, До#) мажор, 2 октавы, 60–80 bpm",
            "Cmaj7: До-Ми-Соль-Си. Dm7: Ре-Фа-Ля-До. G7: Соль-Си-Ре-Фа",
            "Переходы Cmaj7→Dm7→G7→Cmaj7 — G7 хочет разрешиться в Cmaj7",
            "Autumn Leaves: только аккорды левой рукой, один в 2–4 счёта",
        ],
        "links": [
            ("Autumn Leaves ноты", "https://www.musicnotes.com/sheetmusic/mtd.asp?ppn=MN0063367"),
        ]
    },
    {
        "id": "fl1", "cat": "🔵 Флейта", "w": "1–2", "title": "Возобновление",
        "req": "sl1",
        "tasks": [
            "Долгие ноты Ля/Си/До — один вдох, ровно, без вибрато. По 3–4 раза каждую",
            "Гамма До мажор одна октава C4–C5, 50–60 bpm",
            "Простая мелодия наизусть + запись на телефон",
        ],
        "links": []
    },
    {
        "id": "fl2", "cat": "🔵 Флейта", "w": "3–8", "title": "Техника",
        "req": "fl1",
        "tasks": [
            "Долгие ноты хроматически вверх: До, До#... до Соль второй октавы — каждую 4–8 счётов",
            "Гаммы До C4–C6, Соль G4–G6 (Фа#), Ре D4–D6 (Фа#, До#) + арпеджио плавно",
            "Этюд с метрономом. Раз в неделю — запись на телефон",
        ],
        "links": [
            ("Андерсен op.33 (IMSLP)", "https://imslp.org/wiki/24_Etudes,_Op.33_(Andersen,_Joachim)"),
        ]
    },
    {
        "id": "mx1", "cat": "🔵 Микс + Pro Tools", "w": "1–3", "title": "PT: среда + анализ",
        "tasks": [
            "Command+= переключает Edit↔Mix window",
            "Smart Tool = F6. R=запись, B=разрезать, Option+клик=bypass",
            "Clip Gain (треугольник на клипе, до фейдера) vs Input Gain (на канале)",
            "Референс в PT → EQ3 7-Band → 200–400 Гц чистые у хороших миксов. 3 конкретных наблюдения",
        ],
        "links": []
    },
    {
        "id": "mx2", "cat": "🔵 Микс + Pro Tools", "w": "4–6", "title": "PT: сессия + баланс",
        "req": "mx1",
        "tasks": [
            "Dante I/O: Setup→I/O. Naming: 01_Kick, 02_Snare, 10_Bass, 20_Vox",
            "Memory Locations (.) — маркеры куплет/припев/бридж",
            "Option+клик — выключить все инсерты. Грубый баланс только фейдеры и пан",
            "HPF: вокал 80–100 Гц, гитара 100–120, клавиши 120–150. Бас/кик не режь",
            "Узкий Q, свипируй — бочкообразный звук → срезай",
        ],
        "links": []
    },
    {
        "id": "mx3", "cat": "🔵 Микс + Pro Tools", "w": "7–10", "title": "Плотность и динамика",
        "req": "mx2",
        "tasks": [
            "Dyn3 на кике: ratio 4:1, attack 10 мс, GR 3–6 dB. Bypass — плотнее? Значит работает",
            "Aux ← drum group: ratio 8:1, GR 10–15 dB, фейдер в ноль → медленно поднимай",
            "Drum Bus + Bass Bus: сатурация 10–15%",
            "Тест на телефоне — если читается, всё правильно",
        ],
        "links": []
    },
    {
        "id": "mx4", "cat": "🔵 Микс + Pro Tools", "w": "11+", "title": "Реальные проекты",
        "req": "mx3",
        "tasks": [
            "Протокол 8 шагов: 1.PT+шаблон 2.Референс 3.Баланс без плагинов 4.HPF+срез 5.Dyn3+параллельная 6.Реверб умеренно 7.Мониторы→наушники→телефон 8.Пауза 15 мин",
            "Logic vs PT — сравнение workflow на одном материале",
        ],
        "links": []
    },
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
        [InlineKeyboardButton("🔥 Привычки", callback_data="habits_0"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("⚙️ Настройки расписания", callback_data="sched_settings")],
    ])

# ─── RENDER DAY ──────────────────────────────────────────────────────────────

def render_day(date_str, data, page=0):
    evts = data.get("cal", {}).get(date_str, [])
    blocks = get_blocks(date_str, data)
    checked = data.get("days", {}).get(date_str, {}).get("checked", {})
    done = sum(1 for b in blocks if checked.get(b["id"]))
    pct = round(done / len(blocks) * 100) if blocks else 0

    lines = [f"*{day_name(date_str)}*"]
    evt_icons = {"orch": "🎼", "live": "🎤", "busy": "📌", "personal": "👤"}
    for e in evts:
        icon = evt_icons.get(e.get("type"), "•")
        lines.append(f"{icon} {e.get('text', '')}")

    bar_filled = pct // 10
    bar = "█" * bar_filled + "░" * (10 - bar_filled)
    lines.append(f"\n{bar} {pct}% ({done}/{len(blocks)})")
    lines.append("─" * 28)

    # Пагинация — по 8 блоков на страницу
    per_page = 8
    total_pages = (len(blocks) + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))
    visible = blocks[page * per_page:(page + 1) * per_page]

    kb_rows = []
    for b in visible:
        ck = checked.get(b["id"], False)
        mark = "✅" if ck else "⬜"
        label = f"{mark} {b['t']} {b['n']}"
        kb_rows.append([
            InlineKeyboardButton(label, callback_data=f"tog_{date_str}_{b['id']}_{page}"),
            InlineKeyboardButton("✏️", callback_data=f"edit_blk_{date_str}_{b['id']}_{page}"),
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"day_{date_str}_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"day_{date_str}_{page+1}"))
    if nav:
        kb_rows.append(nav)

    kb_rows.append([
        InlineKeyboardButton("➕ Событие", callback_data=f"add_evt_{date_str}"),
        InlineKeyboardButton("➕ Блок", callback_data=f"add_blk_{date_str}"),
    ])
    kb_rows.append([InlineKeyboardButton("← Меню", callback_data="menu")])

    return "\n".join(lines), InlineKeyboardMarkup(kb_rows)

# ─── RENDER METHOD ───────────────────────────────────────────────────────────

def render_method(data):
    prog = data.get("prog", {})
    cats = list(dict.fromkeys(ph["cat"] for ph in PHASES))
    text = "*📖 Методичка*\nНажми на фазу чтобы открыть:"
    kb_rows = []
    for cat in cats:
        kb_rows.append([InlineKeyboardButton(f"─ {cat} ─", callback_data="noop")])
        for ph in PHASES:
            if ph["cat"] != cat:
                continue
            unlocked = is_unlocked(ph, prog)
            tot = len(ph["tasks"])
            dn = sum(1 for i in range(tot) if prog.get(f"{ph['id']}_{i}"))
            pct = round(dn / tot * 100) if tot else 0
            bar = "█" * (pct // 25) + "░" * (4 - pct // 25)
            lock = "" if unlocked else "🔒 "
            label = f"{lock}{ph['title']} [{ph['w']}н] {bar} {dn}/{tot}"
            kb_rows.append([InlineKeyboardButton(label, callback_data=f"phase_{ph['id']}")])
    kb_rows.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return text, InlineKeyboardMarkup(kb_rows)

def render_phase(ph_id, data):
    prog = data.get("prog", {})
    ph = next((p for p in PHASES if p["id"] == ph_id), None)
    if not ph:
        return "Не найдено", InlineKeyboardMarkup([[InlineKeyboardButton("← Назад", callback_data="method")]])

    unlocked = is_unlocked(ph, prog)
    lines = [f"*{ph['cat']} — {ph['title']}*", f"📅 Недели: {ph['w']}"]

    if not unlocked:
        req = next((p for p in PHASES if p["id"] == ph.get("req")), None)
        lines.append(f"\n🔒 Сначала завершить: *{req['title'] if req else ph.get('req')}*")
        return "\n".join(lines), InlineKeyboardMarkup([[InlineKeyboardButton("← Методичка", callback_data="method")]])

    if ph.get("links"):
        lines.append("\n📎 *Материалы:*")
        for name, url in ph["links"]:
            lines.append(f"[{name}]({url})")

    lines.append("\n*Задачи:*")
    kb_rows = []
    for i, task in enumerate(ph["tasks"]):
        done = prog.get(f"{ph_id}_{i}", False)
        mark = "✅" if done else "⬜"
        short = task[:40] + "…" if len(task) > 40 else task
        kb_rows.append([InlineKeyboardButton(f"{mark} {short}", callback_data=f"tog_prog_{ph_id}_{i}")])

    kb_rows.append([InlineKeyboardButton("← Методичка", callback_data="method")])
    return "\n".join(lines), InlineKeyboardMarkup(kb_rows)

# ─── HABITS ──────────────────────────────────────────────────────────────────

def render_habits(data, week_offset=0):
    hab = data.get("hab", {})
    now = now_almaty()
    monday = now - timedelta(days=now.weekday()) + timedelta(weeks=week_offset)
    dates = [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    dn = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    cats = [("piano","🔵 Форте"),("flute","🔵 Флейта"),("mix","🔵 Учёба"),("review","🔴 Ревью")]
    months = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]
    f = datetime.strptime(dates[0], "%Y-%m-%d")
    l = datetime.strptime(dates[6], "%Y-%m-%d")
    text = f"*🔥 Привычки*\n{f.day} {months[f.month-1]} – {l.day} {months[l.month-1]}"
    kb_rows = []
    for cat, lbl in cats:
        kb_rows.append([InlineKeyboardButton(lbl, callback_data="noop")])
        row = []
        for i, d in enumerate(dates):
            on = hab.get(f"{d}_{cat}", False)
            dt = datetime.strptime(d, "%Y-%m-%d")
            day_lbl = f"{'✅' if on else dn[i]}\n{dt.day}"
            row.append(InlineKeyboardButton("✅" if on else dn[i], callback_data=f"tog_hab_{d}_{cat}_{week_offset}"))
        kb_rows.append(row)
    kb_rows.append([
        InlineKeyboardButton("◀", callback_data=f"habits_{week_offset-1}"),
        InlineKeyboardButton("▶", callback_data=f"habits_{week_offset+1}"),
    ])
    kb_rows.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return text, InlineKeyboardMarkup(kb_rows)

# ─── STATS ───────────────────────────────────────────────────────────────────

def render_stats(data):
    hab = data.get("hab", {})
    prog = data.get("prog", {})
    piano = sum(1 for k,v in hab.items() if k.endswith("_piano") and v)
    flute = sum(1 for k,v in hab.items() if k.endswith("_flute") and v)
    mix = sum(1 for k,v in hab.items() if k.endswith("_mix") and v)
    review = sum(1 for k,v in hab.items() if k.endswith("_review") and v)
    streak = 0
    tk = today_key()
    for i in range(365):
        d = (now_almaty() - timedelta(days=i)).strftime("%Y-%m-%d")
        if hab.get(f"{d}_review") or hab.get(f"{d}_piano") or hab.get(f"{d}_mix"):
            streak += 1
        elif d != tk:
            break
    ph_done = sum(1 for ph in PHASES if all(prog.get(f"{ph['id']}_{i}") for i in range(len(ph["tasks"]))))
    text = (f"*📊 Статистика*\n\n"
            f"🔥 Стрик: *{streak}* дней подряд\n\n"
            f"🔵 Фортепиано: *{piano}* сессий\n"
            f"🔵 Флейта: *{flute}* сессий\n"
            f"🔵 Учёба/микс: *{mix}* сессий\n"
            f"🔴 Ревью: *{review}* дней\n\n"
            f"📖 Фаз пройдено: *{ph_done}/{len(PHASES)}*")
    return text, InlineKeyboardMarkup([[InlineKeyboardButton("← Меню", callback_data="menu")]])

# ─── CALENDAR ────────────────────────────────────────────────────────────────

def render_cal_menu(data):
    now = now_almaty()
    text = "*🗓 Календарь — ближайшие дни*"
    kb_rows = []
    row = []
    for i in range(14):
        d = now + timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        evts = data.get("cal", {}).get(ds, [])
        checked = data.get("days", {}).get(ds, {}).get("checked", {})
        blocks = get_blocks(ds, data)
        done = sum(1 for b in blocks if checked.get(b["id"]))
        pct = round(done / len(blocks) * 100) if blocks else 0
        dot = "🟢" if pct == 100 else ("🟡" if pct > 0 else ("🔴" if evts else "⬜"))
        label = f"{dot}{d.day}"
        row.append(InlineKeyboardButton(label, callback_data=f"cal_day_{ds}_0"))
        if len(row) == 7:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    kb_rows.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return text, InlineKeyboardMarkup(kb_rows)

# ─── SCHEDULE SETTINGS ───────────────────────────────────────────────────────

def render_sched_settings():
    text = "*⚙️ Настройки расписания*\n\nЧто хочешь сделать?"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить блок", callback_data="edit_default_list")],
        [InlineKeyboardButton("➕ Добавить блок", callback_data="add_default_blk")],
        [InlineKeyboardButton("🔄 Сбросить к стандарту", callback_data="reset_sched")],
        [InlineKeyboardButton("← Меню", callback_data="menu")],
    ])
    return text, kb

def render_edit_default_list():
    text = "*✏️ Выбери блок для изменения:*"
    kb_rows = []
    for b in DEFAULT_BLOCKS:
        kb_rows.append([InlineKeyboardButton(f"{b['t']} {b['n']}", callback_data=f"edit_default_{b['id']}")])
    kb_rows.append([InlineKeyboardButton("← Назад", callback_data="sched_settings")])
    return text, InlineKeyboardMarkup(kb_rows)

# ─── HANDLERS ────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет, Марк!\n\nТвой персональный планировщик. Выбери раздел:",
        reply_markup=main_menu_kb(),
        parse_mode="Markdown"
    )

async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = load()
    d = q.data

    if d == "menu":
        await q.edit_message_text("Выбери раздел:", reply_markup=main_menu_kb())

    elif d == "today":
        text, kb = render_day(today_key(), data, 0)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d == "tomorrow":
        text, kb = render_day(tomorrow_key(), data, 0)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d.startswith("day_"):
        parts = d.split("_")
        date_str = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 0
        text, kb = render_day(date_str, data, page)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d.startswith("cal_day_"):
        parts = d.split("_")
        date_str = parts[2]
        page = int(parts[3]) if len(parts) > 3 else 0
        text, kb = render_day(date_str, data, page)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d == "cal_menu":
        text, kb = render_cal_menu(data)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d == "method":
        text, kb = render_method(data)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d.startswith("phase_"):
        text, kb = render_phase(d[6:], data)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)

    elif d.startswith("habits_"):
        off = int(d[7:])
        text, kb = render_habits(data, off)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d == "stats":
        text, kb = render_stats(data)
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d == "sched_settings":
        text, kb = render_sched_settings()
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d == "edit_default_list":
        text, kb = render_edit_default_list()
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d.startswith("edit_default_"):
        bid = d[13:]
        blk = next((b for b in DEFAULT_BLOCKS if b["id"] == bid), None)
        if blk:
            ctx.user_data["edit_default_id"] = bid
            ctx.user_data["edit_step"] = "field"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🕐 Время", callback_data="edit_field_t"),
                 InlineKeyboardButton("📝 Название", callback_data="edit_field_n")],
                [InlineKeyboardButton("← Назад", callback_data="edit_default_list")],
            ])
            await q.edit_message_text(
                f"*Редактировать: {blk['t']} {blk['n']}*\nЧто изменить?",
                reply_markup=kb, parse_mode="Markdown"
            )

    elif d.startswith("edit_field_"):
        field = d[11:]
        ctx.user_data["edit_field"] = field
        field_name = "время (формат ЧЧ:ММ)" if field == "t" else "название"
        await q.edit_message_text(f"Введи новое {field_name}:")

    elif d == "reset_sched":
        await q.edit_message_text(
            "Сбросить расписание к стандарту?\nВсе изменения удалятся.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, сбросить", callback_data="reset_confirm"),
                 InlineKeyboardButton("❌ Отмена", callback_data="sched_settings")],
            ])
        )

    elif d == "reset_confirm":
        if "custom_blocks" in data:
            del data["custom_blocks"]
        save(data)
        await q.edit_message_text("✅ Расписание сброшено к стандарту.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Меню", callback_data="menu")]]))

    elif d.startswith("tog_"):
        parts = d.split("_", 2)
        if parts[1] == "prog":
            _, _, rest = d.split("_", 2)
            ph_id, idx = rest.rsplit("_", 1)
            key = f"{ph_id}_{idx}"
            data.setdefault("prog", {})[key] = not data["prog"].get(key, False)
            save(data)
            text, kb = render_phase(ph_id, data)
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)

        elif parts[1] == "hab":
            _, _, rest = d.split("_", 2)
            parts2 = rest.rsplit("_", 1)
            off = int(parts2[1]) if len(parts2) > 1 and parts2[1].lstrip("-").isdigit() else 0
            dc = parts2[0].rsplit("_", 1)
            cat = dc[-1]
            date_str = dc[0]
            key = f"{date_str}_{cat}"
            data.setdefault("hab", {})[key] = not data["hab"].get(key, False)
            save(data)
            text, kb = render_habits(data, off)
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

        else:
            # tog_{date}_{bid}_{page}
            rest = d[4:]
            date_str = rest[:10]
            remainder = rest[11:]
            parts3 = remainder.rsplit("_", 1)
            page = int(parts3[1]) if len(parts3) > 1 and parts3[1].isdigit() else 0
            bid = parts3[0]
            data.setdefault("days", {}).setdefault(date_str, {"checked": {}}).setdefault("checked", {})
            checked = data["days"][date_str]["checked"]
            checked[bid] = not checked.get(bid, False)
            data.setdefault("hab", {})
            if checked[bid]:
                if bid == "piano": data["hab"][f"{date_str}_piano"] = True
                elif bid == "flute": data["hab"][f"{date_str}_flute"] = True
                elif bid in ("mix","ear","solf"): data["hab"][f"{date_str}_mix"] = True
                elif bid == "rev": data["hab"][f"{date_str}_review"] = True
            save(data)
            text, kb = render_day(date_str, data, page)
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

    elif d.startswith("add_evt_"):
        date_str = d[8:]
        ctx.user_data["add_evt_date"] = date_str
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📌 Дела", callback_data=f"evtt_busy_{date_str}"),
             InlineKeyboardButton("👤 Личное", callback_data=f"evtt_personal_{date_str}")],
            [InlineKeyboardButton("← Назад", callback_data=f"day_{date_str}_0")],
        ])
        await q.edit_message_text("Выбери тип события:", reply_markup=kb)

    elif d.startswith("evtt_"):
        parts = d.split("_", 2)
        evt_type = parts[1]
        date_str = parts[2]
        ctx.user_data["add_evt_date"] = date_str
        ctx.user_data["add_evt_type"] = evt_type
        await q.edit_message_text(f"Введи описание события:\n(например: Встреча 14:00)")

    elif d.startswith("add_blk_"):
        date_str = d[8:]
        ctx.user_data["add_blk_date"] = date_str
        ctx.user_data["add_blk_step"] = "time"
        await q.edit_message_text("Введи время нового блока (ЧЧ:ММ):")

    elif d.startswith("edit_blk_"):
        parts = d.split("_")
        date_str = parts[2]
        bid = parts[3]
        page = int(parts[4]) if len(parts) > 4 else 0
        ctx.user_data["edit_blk_date"] = date_str
        ctx.user_data["edit_blk_id"] = bid
        ctx.user_data["edit_blk_page"] = page
        blocks = get_blocks(date_str, data)
        blk = next((b for b in blocks if b["id"] == bid), None)
        if blk:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🕐 Время", callback_data="eblk_t"),
                 InlineKeyboardButton("📝 Название", callback_data="eblk_n")],
                [InlineKeyboardButton("🗑 Удалить блок", callback_data="eblk_del")],
                [InlineKeyboardButton("← Назад", callback_data=f"day_{date_str}_{page}")],
            ])
            await q.edit_message_text(f"*{blk['t']} {blk['n']}*\nЧто изменить?", reply_markup=kb, parse_mode="Markdown")

    elif d.startswith("eblk_"):
        action = d[5:]
        if action == "del":
            date_str = ctx.user_data.get("edit_blk_date")
            bid = ctx.user_data.get("edit_blk_id")
            page = ctx.user_data.get("edit_blk_page", 0)
            blocks = get_blocks(date_str, data)
            blocks = [b for b in blocks if b["id"] != bid]
            data.setdefault("custom_blocks", {})[date_str] = blocks
            save(data)
            text, kb = render_day(date_str, data, page)
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        else:
            ctx.user_data["edit_blk_field"] = action
            fname = "время (ЧЧ:ММ)" if action == "t" else "название"
            await q.edit_message_text(f"Введи новое {fname}:")

    elif d == "noop":
        pass

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load()
    text = update.message.text.strip()

    # Добавление события
    if ctx.user_data.get("add_evt_date") and ctx.user_data.get("add_evt_type"):
        date_str = ctx.user_data.pop("add_evt_date")
        evt_type = ctx.user_data.pop("add_evt_type")
        data.setdefault("cal", {}).setdefault(date_str, []).append({"type": evt_type, "text": text})
        save(data)
        t, kb = render_day(date_str, data, 0)
        await update.message.reply_text("✅ Событие добавлено!", parse_mode="Markdown")
        await update.message.reply_text(t, reply_markup=kb, parse_mode="Markdown")
        return

    # Добавление блока — шаг 1: время
    if ctx.user_data.get("add_blk_step") == "time":
        if re.match(r"^\d{1,2}:\d{2}$", text):
            ctx.user_data["add_blk_time"] = text
            ctx.user_data["add_blk_step"] = "name"
            await update.message.reply_text("Введи название блока:")
        else:
            await update.message.reply_text("Неверный формат. Введи время в формате ЧЧ:ММ:")
        return

    # Добавление блока — шаг 2: название
    if ctx.user_data.get("add_blk_step") == "name":
        date_str = ctx.user_data.pop("add_blk_date")
        t_str = ctx.user_data.pop("add_blk_time")
        ctx.user_data.pop("add_blk_step", None)
        blocks = get_blocks(date_str, data)
        new_blk = {"id": f"custom_{t_str.replace(':','')}", "t": t_str, "n": text, "d": "", "dur": 60}
        blocks = insert_and_shift(blocks, new_blk)
        data.setdefault("custom_blocks", {})[date_str] = blocks
        save(data)
        t2, kb = render_day(date_str, data, 0)
        await update.message.reply_text("✅ Блок добавлен, расписание сдвинуто!", parse_mode="Markdown")
        await update.message.reply_text(t2, reply_markup=kb, parse_mode="Markdown")
        return

    # Редактирование блока дня
    if ctx.user_data.get("edit_blk_field"):
        field = ctx.user_data.pop("edit_blk_field")
        date_str = ctx.user_data.get("edit_blk_date")
        bid = ctx.user_data.get("edit_blk_id")
        page = ctx.user_data.get("edit_blk_page", 0)
        if field == "t" and not re.match(r"^\d{1,2}:\d{2}$", text):
            await update.message.reply_text("Неверный формат. Введи ЧЧ:ММ:")
            ctx.user_data["edit_blk_field"] = field
            return
        blocks = get_blocks(date_str, data)
        for b in blocks:
            if b["id"] == bid:
                b[field] = text
        if field == "t":
            blocks = sorted(blocks, key=lambda b: time_to_min(b["t"]))
        data.setdefault("custom_blocks", {})[date_str] = blocks
        save(data)
        t2, kb = render_day(date_str, data, page)
        await update.message.reply_text("✅ Изменено!", parse_mode="Markdown")
        await update.message.reply_text(t2, reply_markup=kb, parse_mode="Markdown")
        return

    # Редактирование дефолтного блока
    if ctx.user_data.get("edit_field") and ctx.user_data.get("edit_default_id"):
        field = ctx.user_data.pop("edit_field")
        bid = ctx.user_data.pop("edit_default_id")
        if field == "t" and not re.match(r"^\d{1,2}:\d{2}$", text):
            await update.message.reply_text("Неверный формат. Введи ЧЧ:ММ:")
            ctx.user_data["edit_field"] = field
            ctx.user_data["edit_default_id"] = bid
            return
        for b in DEFAULT_BLOCKS:
            if b["id"] == bid:
                b[field] = text
        save(data)
        await update.message.reply_text("✅ Дефолтное расписание обновлено!", reply_markup=main_menu_kb())
        return

    await update.message.reply_text("Используй /start для меню")

# ─── REMINDERS ───────────────────────────────────────────────────────────────

async def send_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = ctx.job.data["chat_id"]
    msg = ctx.job.data["msg"]
    try:
        await ctx.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Reminder error: {e}")

async def daily_review(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = ctx.job.data["chat_id"]
    text = ("*🌙 Ревью дня*\n\n"
            "Запиши быстро:\n\n"
            "✅ Что сделал:\n\n"
            "💡 Что получилось хорошо:\n\n"
            "⚡ Что было сложно:\n\n"
            "📌 Завтра:")
    try:
        await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Review error: {e}")

def setup_reminders(app, chat_id):
    jq = app.job_queue
    reminders = [
        ("07:25", "⏰ *Подъём через 5 минут!*\nВода, умыться, без телефона."),
        ("07:30", "🌅 *Подъём!*\nВода, умыться, выглянуть в окно. Телефон не трогать."),
        ("09:30", "🟣 *Сольфеджио* — 30 мин"),
        ("10:10", "🔵 *Фортепиано* — 45 мин, гаммы и этюд"),
        ("11:05", "🔵 *Флейта* — 30 мин, долгие ноты"),
        ("11:45", "🟣 *Ear Training* — 20 мин"),
        ("12:50", "🔵 *Микс / Pro Tools* — 2 часа"),
        ("19:25", "🔴 *Ревью дня через 5 минут!*"),
        ("21:55", "🌙 *Подготовка ко сну*\nУбери телефон, приглуши свет."),
    ]
    for t_str, msg in reminders:
        h, m = map(int, t_str.split(":"))
        run_time = dtime(hour=h, minute=m, tzinfo=TZ)
        jq.run_daily(send_reminder, time=run_time, data={"chat_id": chat_id, "msg": msg})

    jq.run_daily(daily_review, time=dtime(hour=19, minute=30, tzinfo=TZ), data={"chat_id": chat_id})

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    chat_id = CHAT_ID
    if chat_id:
        setup_reminders(app, chat_id)
        logger.info(f"Reminders set for chat {chat_id}")
    else:
        logger.warning("CHAT_ID not set — reminders disabled")

    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
