import os, json, logging, re
from datetime import datetime, timedelta, time as dtime
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
CHAT_ID = os.environ.get("CHAT_ID", "560819891")
DATA_FILE = "data.json"

def load():
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except:
        return {"days":{}, "cal":{}, "prog":{}, "hab":{}, "finance":[], "notes":[], "tabex_start":None, "tabex_taken":{}}

def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def now_a(): return datetime.now(TZ)
def today_key(): return now_a().strftime("%Y-%m-%d")
def tomorrow_key(): return (now_a()+timedelta(days=1)).strftime("%Y-%m-%d")

def day_label(ds):
    d = datetime.strptime(ds, "%Y-%m-%d")
    N = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    M = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"]
    return f"{N[d.weekday()]}, {d.day} {M[d.month-1]}"

def tmin(t):
    try: h,m=t.split(":"); return int(h)*60+int(m)
    except: return 9999

def mtime(m): return f"{m//60:02d}:{m%60:02d}"

# ─── SCHEDULE ────────────────────────────────────────────────────────────────

DEFAULT = [
    {"id":"wake",  "t":"07:30","n":"Подъём",             "d":"Без телефона — вода, умыться, выглянуть в окно","dur":20,"p":1},
    {"id":"bfast", "t":"07:50","n":"Завтрак + сборы",    "d":"40 мин","dur":40,"p":2},
    {"id":"go",    "t":"08:30","n":"Выезд",              "d":"","dur":30,"p":1},
    {"id":"solf",  "t":"09:00","n":"Сольфеджио",         "d":"60 мин","dur":60,"p":3},
    {"id":"ear",   "t":"10:00","n":"Ear Training",       "d":"30 мин","dur":30,"p":3},
    {"id":"b1",    "t":"10:30","n":"Перерыв",            "d":"10 мин","dur":10,"p":4},
    {"id":"piano", "t":"10:40","n":"Фортепиано",         "d":"60 мин — гаммы, этюд","dur":60,"p":3},
    {"id":"flute", "t":"10:40","n":"Флейта",             "d":"60 мин — долгие ноты, гаммы","dur":60,"p":3},
    {"id":"b2",    "t":"11:40","n":"Перерыв",            "d":"10 мин","dur":10,"p":4},
    {"id":"pt",    "t":"11:50","n":"Pro Tools",          "d":"90 мин — по курсу Udemy","dur":90,"p":3},
    {"id":"lunch", "t":"13:20","n":"Обед + пауза",       "d":"45 мин","dur":45,"p":2},
    {"id":"prac",  "t":"14:05","n":"Практика",           "d":"2 ч — применение изученного","dur":120,"p":3},
    {"id":"b3",    "t":"16:05","n":"Перерыв",            "d":"15 мин","dur":15,"p":4},
    {"id":"read",  "t":"16:20","n":"Чтение / теория",    "d":"60 мин","dur":60,"p":3},
    {"id":"sport", "t":"17:20","n":"Прогулка / спорт",   "d":"45 мин","dur":45,"p":2},
    {"id":"free",  "t":"18:05","n":"Свободное время",    "d":"Личные дела, отдых","dur":55,"p":4},
    {"id":"rev",   "t":"19:00","n":"Ревью дня",          "d":"5 мин — записать в заметки","dur":10,"p":2},
    {"id":"wind",  "t":"21:00","n":"Подготовка ко сну",  "d":"Убрать телефон, приглушить свет","dur":60,"p":2},
    {"id":"slp",   "t":"22:00","n":"Отбой",              "d":"Цель — до 22:00","dur":0,"p":1},
]

LATEST = {"lunch":14*60,"rev":22*60,"wind":22*60,"slp":23*60}

def build_schedule(ds, data):
    dow = datetime.strptime(ds, "%Y-%m-%d").weekday()
    if dow == 6:
        base = [b.copy() for b in DEFAULT if b["id"] in ("wake","bfast","go","lunch","sport","free","rev","wind","slp")]
        for b in base:
            if b["id"]=="free": b["d"]="Полный отдых 🌿"
        return sorted(base, key=lambda x: tmin(x["t"]))
    if dow == 5:
        skip = {"piano","flute","solf","b1"}
    elif dow in (1,3):
        skip = {"piano"}
    else:
        skip = {"flute"}
    base = [b.copy() for b in DEFAULT if b["id"] not in skip]
    evts = data.get("cal",{}).get(ds,[])
    for e in evts:
        if e.get("t_from") and e.get("t_to"):
            eid = "evt_"+re.sub(r"\W","_",e["text"])[:12].lower()
            if not any(b["id"]==eid for b in base):
                fe_s = tmin(e["t_from"]); fe_e = tmin(e["t_to"]); dur = fe_e-fe_s
                new = {"id":eid,"t":e["t_from"],"n":e["text"],"d":f"до {e['t_to']}","dur":dur,"p":1,"_evt":True}
                new_base = []
                p3q = []
                push = fe_e
                inserted = False
                for b in sorted(base, key=lambda x: tmin(x["t"])):
                    bm = tmin(b["t"]); be = bm+b.get("dur",30); p = b.get("p",3)
                    if not inserted and bm >= fe_s:
                        new_base.append(new); inserted = True
                    if inserted and not b.get("_evt"):
                        if bm < push:
                            if p==1: new_base.append(b)
                            elif p==2:
                                if b["id"]=="lunch" and fe_s<=bm<=fe_s+240: new_base.append(b)
                                else: b=b.copy(); b["t"]=mtime(push); push+=b.get("dur",30); new_base.append(b)
                            elif p==3: p3q.append(b)
                            elif p==4: pass
                        else: new_base.append(b)
                    else:
                        if not inserted: new_base.append(b)
                if not inserted: new_base.append(new)
                cur = push
                for b in p3q:
                    if cur+b.get("dur",30) <= 22*60:
                        b=b.copy(); b["t"]=mtime(cur); cur+=b.get("dur",30)+10; new_base.append(b)
                base = sorted(new_base, key=lambda x: tmin(x["t"]))
    result = []
    for b in base:
        lim = LATEST.get(b["id"])
        if lim and tmin(b["t"])>lim: b=b.copy(); b["t"]=mtime(lim)
        result.append(b)
    return sorted(result, key=lambda x: tmin(x["t"]))

# ─── PHASES ──────────────────────────────────────────────────────────────────

PHASES = [
    {"id":"sl1","cat":"🟣 Сольфеджио","w":"1–4","title":"Ноты и ритм",
     "tasks":["Линейки: Ми-Соль-Си-Ре-Фа (Мама Гоши Сделала Рисовую Фигуру)","Промежутки: Фа-Ля-До-Ми","Ритм: целая=4, половинная=2, четверть=1, восьмая=0.5 — отстукивай по колену","Петь мелодию по нотам с фортепиано и без"],
     "links":[("📖 musictheory.net/lessons","https://www.musictheory.net/lessons"),("🎯 Тренажёр нот","https://www.musictheory.net/exercises/note")]},
    {"id":"sl2","cat":"🟣 Сольфеджио","w":"5–10","title":"Интервалы и пение","req":"sl1",
     "tasks":["Петь гамму До мажор по нотам","Диктант — записать мелодию на слух","Интонировать интервалы: терция, квинта, октава"],
     "links":[("🎯 Тренажёр нот","https://www.musictheory.net/exercises/note")]},
    {"id":"sl3","cat":"🟣 Сольфеджио","w":"11–20","title":"Тональности","req":"sl2",
     "tasks":["Диезы: Фа-До-Соль-Ре-Ля-Ми-Си. Бемоли: обратно. 1 диез=Соль, 2=Ре, 3=Ля","Хроматическая гамма","Транспозиция мелодии"],
     "links":[]},
    {"id":"et1","cat":"🟡 Ear Training","w":"1–4","title":"Интервалы","req":"sl1",
     "tasks":["Ассоциации: терция=Подмосковные вечера, квинта=Star Wars, октава=Somewhere Over the Rainbow","Тренажёр интервалов — 20 мин, записывай % угадывания","Петь интервалы от любой ноты вверх и вниз"],
     "links":[("🎯 Ear interval","https://www.musictheory.net/exercises/ear-interval")]},
    {"id":"et2","cat":"🟡 Ear Training","w":"5–8","title":"Аккорды и лады","req":"et1",
     "tasks":["Мажор=радостно, минор=грустно, G7=напряжённо — 10–15 аккордов за сессию","Анализ трека: тональность + первые 4 аккорда"],
     "links":[("🎯 Ear chord","https://www.musictheory.net/exercises/ear-chord")]},
    {"id":"et3","cat":"🟡 Ear Training","w":"9–16","title":"Тембр и частоты","req":"et2",
     "tasks":["100Гц=бум, 200–400=каша, 1–3кГц=присутствие, 5–8кГц=резкость","Quiztones — 30 мин в день","Слышать компрессию без плагина"],
     "links":[("🎯 Quiztones","https://www.quiztones.com")]},
    {"id":"pn1","cat":"🔵 Фортепиано","w":"1–4","title":"Постановка рук","req":"sl1",
     "tasks":["Разогрев 5 мин: сжимай пальцы, вращай запястья","До-Ре-Ми-Фа-Соль каждой рукой — большой на До (C4), медленно с весом","Бах Менуэт BWV Anh.114: по 2 такта правая → левая → вместе"],
     "links":[("🎼 Ноты Менуэта (IMSLP)","https://imslp.org/wiki/Minuet_in_G_major,_BWV_Anh.114_(Bach,_Johann_Sebastian)")]},
    {"id":"pn2","cat":"🔵 Фортепиано","w":"5–10","title":"Гаммы + аккорды","req":"pn1",
     "tasks":["Гамма До мажор двумя руками 2 октавы, метроном 60 bpm","Трезвучия До–Фа–Соль с левым басом","По 4 такта с метрономом: правая → левая → вместе"],
     "links":[("🎼 Ноты Менуэта (IMSLP)","https://imslp.org/wiki/Minuet_in_G_major,_BWV_Anh.114_(Bach,_Johann_Sebastian)")]},
    {"id":"pn3","cat":"🔵 Фортепиано","w":"11–20","title":"Джаз","req":"pn2",
     "tasks":["Гаммы Соль (Фа#) и Ре (Фа#, До#) — 2 октавы, 60–80 bpm","Cmaj7/Dm7/G7 — аппликатура и переходы","Autumn Leaves: аккорды левой рукой"],
     "links":[("🎼 Autumn Leaves","https://www.musicnotes.com/sheetmusic/mtd.asp?ppn=MN0063367")]},
    {"id":"fl1","cat":"🔵 Флейта","w":"1–2","title":"Возобновление","req":"sl1",
     "tasks":["Долгие ноты Ля/Си/До — один вдох, ровно, без вибрато","Гамма До мажор C4–C5, 50–60 bpm","Простая мелодия наизусть + запись на телефон"],
     "links":[]},
    {"id":"fl2","cat":"🔵 Флейта","w":"3–8","title":"Техника","req":"fl1",
     "tasks":["Долгие ноты хроматически — разогрев каждый раз","Гаммы До/Соль/Ре двух октав + арпеджио","Этюд с метрономом, раз в неделю — запись"],
     "links":[("🎼 Андерсен op.33","https://imslp.org/wiki/24_Etudes,_Op.33_(Andersen,_Joachim)")]},
    {"id":"pt1","cat":"🔵 Pro Tools","w":"1–2","title":"Установка и первая сессия",
     "tasks":["Лек.01 (13 мин): Установка, активация Avid, аудиодрайвер","Лек.02 (8 мин): Создание сессии — sample rate, bit depth, путь","Лек.03 (21 мин): Аудиотреки — создание, именование, запись"],
     "links":[("🎥 Курс Udemy","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/")]},
    {"id":"pt2","cat":"🔵 Pro Tools","w":"2–3","title":"Режимы и Fades","req":"pt1",
     "tasks":["Лек.04 (25 мин): Edit Modes — Shuffle/Slip/Spot/Grid, Smart Tool=F6","Лек.18 (6 мин): Clip Gain (треугольник на клипе) vs Volume Automation","Лек.19 (11 мин): Edit Modes Recap, Relative Grid Mode","Шорткаты: Command+=Edit↔Mix, R=запись, B=разрезать, Option+клик=bypass"],
     "links":[("🎥 Курс Udemy","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/")]},
    {"id":"pt3","cat":"🔵 Pro Tools","w":"3–4","title":"MIDI, EQ и Inserts","req":"pt2",
     "tasks":["Лек.05 (28 мин): MIDI ноты и Quantize — Piano Roll","Лек.06 (14 мин): Inserts и EQ3 7-Band — HPF, shelf","Практика HPF: вокал 80–100Гц, гитара 100–120, клавиши 120–150"],
     "links":[("🎥 Курс Udemy","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/")]},
    {"id":"pt4","cat":"🔵 Pro Tools","w":"4–5","title":"Эффекты, Sends, Busses","req":"pt3",
     "tasks":["Лек.07 (30 мин): Effects, Sends, Busses — Aux треки, шины","Лек.11 (9 мин): Pre vs Post Fader Sends","Лек.08 (22 мин): Printing to Audio Track"],
     "links":[("🎥 Курс Udemy","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/")]},
    {"id":"pt5","cat":"🔵 Pro Tools","w":"5–6","title":"Автоматизация и запись","req":"pt4",
     "tasks":["Лек.13 (9 мин): Volume Automation — Write/Touch/Latch/Read","Лек.14 (5 мин): More on Automation","Лек.17 (25 мин): Playlists для записи нескольких дублей"],
     "links":[("🎥 Курс Udemy","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/")]},
    {"id":"pt6","cat":"🔵 Pro Tools","w":"6–7","title":"Организация и импорт","req":"pt5",
     "tasks":["Лек.21 (9 мин): Backup сессии","Лек.23 (7 мин): Импорт аудио","Лек.24 (12 мин): Naming — 01_Kick, 02_Snare, 10_Bass, 20_Vox","Лек.25 (14 мин): Auxiliary Tracks и Routing Folders"],
     "links":[("🎥 Курс Udemy","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/")]},
    {"id":"pt7","cat":"🔵 Pro Tools","w":"7–8","title":"Сведение: EQ и баланс","req":"pt6",
     "tasks":["Лек.26 (17 мин): Editing and Balancing — грубый баланс без плагинов","Reverb and Delay (24 мин): реверб и дилей через Aux","Delay and Compression (23 мин): Dyn3 ratio 4:1, attack 10мс, GR 3–6 dB"],
     "links":[("🎥 Курс Udemy","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/")]},
    {"id":"pt8","cat":"🔵 Pro Tools","w":"8–9","title":"Динамика и баунс","req":"pt7",
     "tasks":["Sends Automation (17 мин)","Loudness Units (11 мин): LUFS — стриминг -14 LUFS, -1 dBTP","Bouncing a Mix (12 мин): финальный баунс — форматы, настройки"],
     "links":[("🎥 Курс Udemy","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/")]},
    {"id":"pt9","cat":"🔵 Pro Tools","w":"9–10","title":"Продвинутые инструменты","req":"pt8",
     "tasks":["Consolidate & Clip Grouping (6 мин)","AudioSuite (4 мин): оффлайн-обработка","Strip Silence (6 мин), Tab to Transients (3 мин)","Batch Rename (7 мин), Import Session Data (4 мин)","Saving a Session Template (3 мин)"],
     "links":[("🎥 Курс Udemy","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/")]},
    {"id":"pt10","cat":"🔵 Pro Tools","w":"11+","title":"Реальные проекты","req":"pt9",
     "tasks":["Mixing, Reverb, EQ, Compression (33 мин): полный цикл","Signal Chain Recap (8 мин): порядок обработки","Протокол 8 шагов: PT+шаблон → Референс → Баланс → HPF+срез → Dyn3+параллельная → Реверб → Мониторы→наушники→телефон → Пауза 15 мин"],
     "links":[("🎥 Курс Udemy","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/")]},
]

def unlocked(ph, prog):
    req = ph.get("req")
    if not req: return True
    r = next((p for p in PHASES if p["id"]==req), None)
    return r and all(prog.get(f"{r['id']}_{i}") for i in range(len(r["tasks"])))

# ─── FINANCE ─────────────────────────────────────────────────────────────────

EXP_CATS = ["🍕 Еда","🚕 Транспорт","🛍 Покупки","🎁 Подарки","✈️ Путешествия","💊 Здоровье","🎮 Развлечения","🗑 Бессмысленное","📦 Другое"]
INC_CATS = ["🎼 ЭСО","🎤 Прокат","💻 Фриланс","💸 Возврат долга","📦 Другое"]

def render_finance_menu(data):
    fin = data.get("finance", [])
    now = now_a()
    month_exp = sum(f["amount"] for f in fin if f["type"]=="exp" and f["date"][:7]==now.strftime("%Y-%m"))
    month_inc = sum(f["amount"] for f in fin if f["type"]=="inc" and f["date"][:7]==now.strftime("%Y-%m"))
    year_exp = sum(f["amount"] for f in fin if f["type"]=="exp" and f["date"][:4]==str(now.year))
    year_inc = sum(f["amount"] for f in fin if f["type"]=="inc" and f["date"][:4]==str(now.year))
    month_bal = month_inc - month_exp
    year_bal = year_inc - year_exp
    bal_sign = "+" if month_bal >= 0 else ""
    ybal_sign = "+" if year_bal >= 0 else ""

    months = ["январь","февраль","март","апрель","май","июнь","июль","август","сентябрь","октябрь","ноябрь","декабрь"]
    text = (f"*💰 Финансы*\n\n"
            f"*{months[now.month-1].capitalize()} {now.year}:*\n"
            f"📈 Доходы: {month_inc:,.0f} ₸\n"
            f"📉 Расходы: {month_exp:,.0f} ₸\n"
            f"💼 Баланс: {bal_sign}{month_bal:,.0f} ₸\n\n"
            f"*{now.year} год:*\n"
            f"📈 Доходы: {year_inc:,.0f} ₸\n"
            f"📉 Расходы: {year_exp:,.0f} ₸\n"
            f"💼 Баланс: {ybal_sign}{year_bal:,.0f} ₸")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить расход", callback_data="fin_add_exp"),
         InlineKeyboardButton("➕ Добавить доход", callback_data="fin_add_inc")],
        [InlineKeyboardButton("📊 По категориям", callback_data="fin_cats"),
         InlineKeyboardButton("📋 История", callback_data="fin_history_0")],
        [InlineKeyboardButton("← Меню", callback_data="menu")],
    ])
    return text, kb

def render_fin_cats(data):
    fin = data.get("finance", [])
    now = now_a()
    month = now.strftime("%Y-%m")
    lines = [f"*📊 По категориям — {now.strftime('%m.%Y')}*\n"]
    lines.append("*Расходы:*")
    exp_by_cat = {}
    for f in fin:
        if f["type"]=="exp" and f["date"][:7]==month:
            exp_by_cat[f["cat"]] = exp_by_cat.get(f["cat"],0) + f["amount"]
    if exp_by_cat:
        for cat,amt in sorted(exp_by_cat.items(), key=lambda x: -x[1]):
            lines.append(f"{cat}: {amt:,.0f} ₸")
    else:
        lines.append("Нет расходов")
    lines.append("\n*Доходы:*")
    inc_by_cat = {}
    for f in fin:
        if f["type"]=="inc" and f["date"][:7]==month:
            inc_by_cat[f["cat"]] = inc_by_cat.get(f["cat"],0) + f["amount"]
    if inc_by_cat:
        for cat,amt in sorted(inc_by_cat.items(), key=lambda x: -x[1]):
            lines.append(f"{cat}: {amt:,.0f} ₸")
    else:
        lines.append("Нет доходов")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("← Финансы", callback_data="finance")]])
    return "\n".join(lines), kb

def render_fin_history(data, pg=0):
    fin = data.get("finance", [])
    fin_sorted = sorted(fin, key=lambda x: x["date"], reverse=True)
    per = 10; total = max(1,(len(fin_sorted)+per-1)//per)
    pg = max(0,min(pg,total-1))
    visible = fin_sorted[pg*per:(pg+1)*per]
    lines = [f"*📋 История ({pg+1}/{total})*\n"]
    for f in visible:
        sign = "📉" if f["type"]=="exp" else "📈"
        lines.append(f"{sign} {f['date']} | {f['cat']}\n    {f['name']} — {f['amount']:,.0f} ₸")
    nav = []
    if pg > 0: nav.append(InlineKeyboardButton("◀", callback_data=f"fin_history_{pg-1}"))
    if pg < total-1: nav.append(InlineKeyboardButton("▶", callback_data=f"fin_history_{pg+1}"))
    kb_rows = []
    if nav: kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("← Финансы", callback_data="finance")])
    return "\n".join(lines), InlineKeyboardMarkup(kb_rows)

# ─── NOTES ───────────────────────────────────────────────────────────────────

def render_notes(data, pg=0):
    notes = data.get("notes", [])
    per = 8; total = max(1,(len(notes)+per-1)//per)
    pg = max(0,min(pg,total-1))
    visible = notes[pg*per:(pg+1)*per]
    text = f"*📝 Заметки* ({len(notes)} всего)\n\n"
    if not notes: text += "_Пока нет заметок_"
    kb = []
    for i, n in enumerate(visible):
        idx = pg*per+i
        short = n["text"][:40]+"…" if len(n["text"])>40 else n["text"]
        kb.append([
            InlineKeyboardButton(f"📌 {short}", callback_data=f"note_view_{idx}"),
            InlineKeyboardButton("🗑", callback_data=f"note_del_{idx}"),
        ])
    nav = []
    if pg > 0: nav.append(InlineKeyboardButton("◀", callback_data=f"notes_{pg-1}"))
    if pg < total-1: nav.append(InlineKeyboardButton("▶", callback_data=f"notes_{pg+1}"))
    if nav: kb.append(nav)
    kb.append([InlineKeyboardButton("➕ Новая заметка", callback_data="note_add")])
    kb.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return text, InlineKeyboardMarkup(kb)

def render_note_view(data, idx):
    notes = data.get("notes", [])
    if idx >= len(notes):
        return "Заметка не найдена", InlineKeyboardMarkup([[InlineKeyboardButton("← Заметки", callback_data="notes_0")]])
    n = notes[idx]
    text = f"*📌 Заметка*\n\n{n['text']}\n\n_{n['date']}_"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Редактировать", callback_data=f"note_edit_{idx}"),
         InlineKeyboardButton("🗑 Удалить", callback_data=f"note_del_{idx}")],
        [InlineKeyboardButton("← Заметки", callback_data="notes_0")],
    ])
    return text, kb

# ─── TABEX ───────────────────────────────────────────────────────────────────

TABEX = {
    **{d: ["08:00","10:00","12:00","14:00","16:00","18:00","20:00","22:00"] for d in range(1,4)},
    **{d: ["08:00","10:30","13:00","15:30","18:00","20:30"] for d in range(4,13)},
    **{d: ["08:00","11:00","14:00","17:00","20:00"] for d in range(13,17)},
    **{d: ["08:00","13:00","20:00"] for d in range(17,21)},
    **{d: ["08:00","20:00"] for d in range(21,26)},
}

def tabex_day(data):
    start = data.get("tabex_start")
    if not start: return None
    s = datetime.strptime(start,"%Y-%m-%d").replace(tzinfo=TZ)
    t = datetime.strptime(today_key(),"%Y-%m-%d").replace(tzinfo=TZ)
    return (t-s).days+1

def render_tabex(data):
    day = tabex_day(data)
    if not day or day > 25:
        text = ("*🚭 Бросаю курить — Табекс*\n\n"
                "Курс 25 дней по схеме производителя.\n"
                "Уведомления приходят автоматически.\n\n"
                "⚠️ После 5-го дня — полный отказ от сигарет.\n\n"
                "Когда начинаем?")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Начинаю сегодня", callback_data="tabex_start")],
            [InlineKeyboardButton("← Меню", callback_data="menu")],
        ])
        return text, kb
    scheme = TABEX.get(day, [])
    taken = data.get("tabex_taken",{}).get(today_key(),[])
    now = now_a(); cur_min = now.hour*60+now.minute
    text = f"*🚭 Табекс — День {day}/25*\nТаблеток: {len(taken)}/{len(scheme)}\n\n"
    for t in scheme:
        if t in taken: mark="✅"
        elif tmin(t) <= cur_min: mark="⚠️"
        else: mark="⬜"
        text += f"{mark} {t}\n"
    if day == 5: text += "\n⚠️ *Сегодня полный отказ от сигарет!*"
    if day > 5: text += f"\n\n🚭 Без сигарет: *{day-5}* дней"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Принял таблетку", callback_data="tabex_took")],
        [InlineKeyboardButton(f"📅 Осталось {25-day} дней", callback_data="noop")],
        [InlineKeyboardButton("🔄 Сбросить курс", callback_data="tabex_reset")],
        [InlineKeyboardButton("← Меню", callback_data="menu")],
    ])
    return text, kb

# ─── TEXTS ───────────────────────────────────────────────────────────────────

GUIDE_TEXT = """*📋 Памятка по категориям*

🔴 *P1 — Фиксированные* (не двигаются)
→ Подъём, отбой, важные встречи, события с временем

🟡 *P2 — Гибкие обязательные* (двигаются, не удаляются)
→ Завтрак, обед, ревью, сон
→ Обед внутри события — остаётся если логично (до 14:00)

🟢 *P3 — Учёба* (переносятся в свободные слоты)
→ Сольфеджио, форте, флейта, ear, PT, практика, чтение

⚪ *P4 — Заполнители* (удаляются если нет места)
→ Перерывы, свободное время

─────────────────────
*Добавить событие:*
➕ → тип → напишите: `Название 14:00–16:00`
Расписание сдвинется автоматически."""

SLEEP_TEXT = """*😴 Сон и фокус*

*🌅 Утро — первые 30 минут:*
• Подъём в одно время — даже в выходные
• Сразу 1–2 стакана воды
• Телефон — только через 20 мин
• Открой шторы — запускает циркадный ритм

*☀️ День — фокус:*
• Правило 25+5: 25 мин работа, 5 мин перерыв
• Перерыв = встать + вода (не телефон)
• Кофе не раньше 09:30 и не позже 15:00

*🌙 Вечер:*
• За 1 час до сна — приглуши свет
• Телефон убираем в 21:00
• Не ешь за 2 часа до сна
• Температура 18–20°C — идеально
• Не можешь заснуть: дыхание 4-7-8

*⚡ Сбился режим:*
Не отсыпайся — встань в запланированное время.
2–3 дня и ритм восстановится."""

# ─── MAIN MENU ───────────────────────────────────────────────────────────────

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Сегодня", callback_data="today"),
         InlineKeyboardButton("📅 Завтра",  callback_data="tomorrow")],
        [InlineKeyboardButton("🗓 Календарь", callback_data="cal_menu"),
         InlineKeyboardButton("📖 Методичка", callback_data="method")],
        [InlineKeyboardButton("🔥 Привычки", callback_data="habits_0"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("💰 Финансы", callback_data="finance"),
         InlineKeyboardButton("📝 Заметки", callback_data="notes_0")],
        [InlineKeyboardButton("✏️ Редактор", callback_data="editor"),
         InlineKeyboardButton("📋 Памятка", callback_data="guide")],
        [InlineKeyboardButton("😴 Сон и фокус", callback_data="sleep_tips"),
         InlineKeyboardButton("🚭 Табекс", callback_data="tabex_menu")],
    ])

# ─── DAY VIEW ────────────────────────────────────────────────────────────────

def render_day(ds, data, pg=0):
    dow = datetime.strptime(ds,"%Y-%m-%d").weekday()
    rot = ["Пн: Сольф+Форте+Слух+PT","Вт: Сольф+Флейта+Слух+PT","Ср: Сольф+Форте+Слух+PT",
           "Чт: Сольф+Флейта+Слух+PT","Пт: Сольф+Форте+Слух+PT","Сб: PT+Слух","Вс: Отдых 🌿"][dow]
    blocks = build_schedule(ds, data)
    evts = data.get("cal",{}).get(ds,[])
    checked = data.get("days",{}).get(ds,{}).get("checked",{})
    done = sum(1 for b in blocks if checked.get(b["id"]))
    pct = round(done/len(blocks)*100) if blocks else 0
    bar = "█"*(pct//10)+"░"*(10-pct//10)
    lines = [f"*{day_label(ds)}*", f"_{rot}_"]
    for e in evts:
        icon = {"busy":"📌","personal":"👤"}.get(e.get("type"),"•")
        tr = f" {e['t_from']}–{e['t_to']}" if e.get("t_from") else ""
        lines.append(f"{icon} {e.get('text','')}{tr}")
    lines.append(f"\n{bar} {pct}% ({done}/{len(blocks)})\n{'─'*28}")
    per=8; total=(len(blocks)+per-1)//per
    pg=max(0,min(pg,total-1))
    visible=blocks[pg*per:(pg+1)*per]
    kb=[]
    for b in visible:
        ck=checked.get(b["id"],False)
        kb.append([InlineKeyboardButton(f"{'✅' if ck else '⬜'} {b['t']} {b['n']}", callback_data=f"tog_{ds}_{b['id']}_{pg}")])
    nav=[]
    if pg>0: nav.append(InlineKeyboardButton("◀", callback_data=f"day_{ds}_{pg-1}"))
    if pg<total-1: nav.append(InlineKeyboardButton("▶", callback_data=f"day_{ds}_{pg+1}"))
    if nav: kb.append(nav)
    kb.append([InlineKeyboardButton("➕ Добавить событие", callback_data=f"add_evt_{ds}")])
    kb.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)

# ─── METHOD ──────────────────────────────────────────────────────────────────

def render_method(data):
    prog=data.get("prog",{})
    cats=list(dict.fromkeys(p["cat"] for p in PHASES))
    kb=[]
    for cat in cats:
        kb.append([InlineKeyboardButton(f"── {cat} ──", callback_data="noop")])
        for ph in PHASES:
            if ph["cat"]!=cat: continue
            ul=unlocked(ph,prog); tot=len(ph["tasks"])
            dn=sum(1 for i in range(tot) if prog.get(f"{ph['id']}_{i}"))
            pct=round(dn/tot*100) if tot else 0
            bar="█"*(pct//25)+"░"*(4-pct//25)
            label=f"{'🔒 ' if not ul else ''}{ph['title']} [{ph['w']}н] {bar} {dn}/{tot}"
            kb.append([InlineKeyboardButton(label, callback_data=f"phase_{ph['id']}")])
    kb.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return "*📖 Методичка*\nНажми на фазу:", InlineKeyboardMarkup(kb)

def render_phase(pid, data):
    prog=data.get("prog",{})
    ph=next((p for p in PHASES if p["id"]==pid),None)
    if not ph: return "Не найдено", InlineKeyboardMarkup([[InlineKeyboardButton("←", callback_data="method")]])
    ul=unlocked(ph,prog)
    lines=[f"*{ph['cat']} — {ph['title']}*", f"📅 Недели: {ph['w']}"]
    if not ul:
        r=next((p for p in PHASES if p["id"]==ph.get("req")),None)
        lines.append(f"\n🔒 Сначала: *{r['title'] if r else ph.get('req')}*")
        return "\n".join(lines), InlineKeyboardMarkup([[InlineKeyboardButton("← Методичка", callback_data="method")]])
    if ph.get("links"):
        lines.append("\n📎 *Материалы:*")
        for name,url in ph["links"]: lines.append(f"[{name}]({url})")
    lines.append("\n*Задачи:*")
    kb=[]
    for i,task in enumerate(ph["tasks"]):
        done=prog.get(f"{pid}_{i}",False)
        first=task.split("\n")[0]; short=first[:48]+"…" if len(first)>48 else first
        kb.append([InlineKeyboardButton(f"{'✅' if done else '⬜'} {short}", callback_data=f"tog_prog_{pid}_{i}")])
    kb.append([InlineKeyboardButton("← Методичка", callback_data="method")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)

# ─── HABITS / STATS ──────────────────────────────────────────────────────────

def render_habits(data, off=0):
    hab=data.get("hab",{})
    mon=now_a()-timedelta(days=now_a().weekday())+timedelta(weeks=off)
    dates=[(mon+timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    dn=["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    months=["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]
    f=datetime.strptime(dates[0],"%Y-%m-%d"); l=datetime.strptime(dates[6],"%Y-%m-%d")
    cats=[("piano","🔵 Форте"),("flute","🔵 Флейта"),("mix","🔵 Учёба"),("review","🔴 Ревью")]
    kb=[]
    for cat,lbl in cats:
        kb.append([InlineKeyboardButton(lbl, callback_data="noop")])
        kb.append([InlineKeyboardButton("✅" if hab.get(f"{d}_{cat}") else dn[i], callback_data=f"tog_hab_{d}_{cat}_{off}") for i,d in enumerate(dates)])
    kb.append([InlineKeyboardButton("◀", callback_data=f"habits_{off-1}"), InlineKeyboardButton("▶", callback_data=f"habits_{off+1}")])
    kb.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return f"*🔥 Привычки*\n{f.day} {months[f.month-1]} – {l.day} {months[l.month-1]}", InlineKeyboardMarkup(kb)

def render_stats(data):
    hab=data.get("hab",{}); prog=data.get("prog",{})
    streak=0; tk=today_key()
    for i in range(365):
        d=(now_a()-timedelta(days=i)).strftime("%Y-%m-%d")
        if hab.get(f"{d}_review") or hab.get(f"{d}_piano") or hab.get(f"{d}_mix"): streak+=1
        elif d!=tk: break
    ph_done=sum(1 for ph in PHASES if all(prog.get(f"{ph['id']}_{i}") for i in range(len(ph["tasks"]))))
    text=(f"*📊 Статистика*\n\n🔥 Стрик: *{streak}* дней\n\n"
          f"🔵 Фортепиано: *{sum(1 for k,v in hab.items() if k.endswith('_piano') and v)}* сессий\n"
          f"🔵 Флейта: *{sum(1 for k,v in hab.items() if k.endswith('_flute') and v)}* сессий\n"
          f"🔵 Учёба: *{sum(1 for k,v in hab.items() if k.endswith('_mix') and v)}* сессий\n"
          f"🔴 Ревью: *{sum(1 for k,v in hab.items() if k.endswith('_review') and v)}* дней\n\n"
          f"📖 Фаз пройдено: *{ph_done}/{len(PHASES)}*")
    return text, InlineKeyboardMarkup([[InlineKeyboardButton("← Меню", callback_data="menu")]])

def render_cal(data):
    kb=[]; row=[]
    for i in range(14):
        d=now_a()+timedelta(days=i); ds=d.strftime("%Y-%m-%d")
        evts=data.get("cal",{}).get(ds,[])
        checked=data.get("days",{}).get(ds,{}).get("checked",{})
        blocks=build_schedule(ds,data)
        done=sum(1 for b in blocks if checked.get(b["id"]))
        pct=round(done/len(blocks)*100) if blocks else 0
        dot="🟢" if pct==100 else("🟡" if pct>0 else("🔴" if evts else "⬜"))
        row.append(InlineKeyboardButton(f"{dot}{d.day}", callback_data=f"day_{ds}_0"))
        if len(row)==7: kb.append(row); row=[]
    if row: kb.append(row)
    kb.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return "*🗓 Календарь*", InlineKeyboardMarkup(kb)

def render_editor():
    kb=[]
    for b in DEFAULT:
        p_icon=["","🔴","🟡","🟢","⚪"][b.get("p",3)]
        kb.append([InlineKeyboardButton(f"{p_icon} {b['t']} — {b['n']}", callback_data=f"ed_blk_{b['id']}")])
    kb.append([InlineKeyboardButton("➕ Добавить блок", callback_data="ed_add")])
    kb.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return "*✏️ Редактор расписания*", InlineKeyboardMarkup(kb)

def render_edit_block(bid):
    b=next((x for x in DEFAULT if x["id"]==bid),None)
    if not b: return "Не найдено", InlineKeyboardMarkup([[InlineKeyboardButton("←", callback_data="editor")]])
    pn={1:"🔴 Фиксированный",2:"🟡 Гибкий",3:"🟢 Учёба",4:"⚪ Заполнитель"}
    text=f"*{b['t']} — {b['n']}*\nПриоритет: {pn.get(b.get('p',3))}"
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 Время", callback_data=f"ed_f_t_{bid}"),
         InlineKeyboardButton("📝 Название", callback_data=f"ed_f_n_{bid}")],
        [InlineKeyboardButton("⬆️ P выше", callback_data=f"ed_p_up_{bid}"),
         InlineKeyboardButton("⬇️ P ниже", callback_data=f"ed_p_dn_{bid}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"ed_del_{bid}")],
        [InlineKeyboardButton("← Назад", callback_data="editor")],
    ])
    return text, kb

# ─── HANDLERS ────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет, Марк!\n\nВыбери раздел:", reply_markup=main_kb(), parse_mode="Markdown")

async def myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Твой chat\\_id: `{update.effective_chat.id}`", parse_mode="Markdown")

async def btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    data=load(); d=q.data

    # NAVIGATION
    if d=="menu": await q.edit_message_text("Выбери раздел:", reply_markup=main_kb())
    elif d=="today":
        t,kb=render_day(today_key(),data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="tomorrow":
        t,kb=render_day(tomorrow_key(),data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("day_"):
        p=d.split("_"); ds=p[1]; pg=int(p[2]) if len(p)>2 else 0
        t,kb=render_day(ds,data,pg); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="cal_menu":
        t,kb=render_cal(data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="method":
        t,kb=render_method(data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("phase_"):
        t,kb=render_phase(d[6:],data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown",disable_web_page_preview=True)
    elif d.startswith("habits_"):
        t,kb=render_habits(data,int(d[7:])); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="stats":
        t,kb=render_stats(data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="guide":
        await q.edit_message_text(GUIDE_TEXT,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Меню",callback_data="menu")]]),parse_mode="Markdown")
    elif d=="sleep_tips":
        await q.edit_message_text(SLEEP_TEXT,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Меню",callback_data="menu")]]),parse_mode="Markdown")

    # FINANCE
    elif d=="finance":
        t,kb=render_finance_menu(data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="fin_cats":
        t,kb=render_fin_cats(data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("fin_history_"):
        pg=int(d[12:]); t,kb=render_fin_history(data,pg); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="fin_add_exp":
        ctx.user_data["fin_type"]="exp"
        ctx.user_data["fin_step"]="name"
        await q.edit_message_text("💸 *Новый расход*\n\nВведи название расхода:", parse_mode="Markdown")
    elif d=="fin_add_inc":
        ctx.user_data["fin_type"]="inc"
        ctx.user_data["fin_step"]="name"
        await q.edit_message_text("💰 *Новый доход*\n\nВведи название дохода:", parse_mode="Markdown")
    elif d.startswith("fin_cat_"):
        cat=d[8:]; ctx.user_data["fin_cat"]=cat; ctx.user_data["fin_step"]="amount"
        await q.edit_message_text(f"Категория: *{cat}*\n\nВведи сумму (в тенге):", parse_mode="Markdown")

    # NOTES
    elif d.startswith("notes_"):
        pg=int(d[6:]); t,kb=render_notes(data,pg); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("note_view_"):
        idx=int(d[10:]); t,kb=render_note_view(data,idx); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("note_del_"):
        idx=int(d[9:]); notes=data.get("notes",[]); 
        if idx<len(notes): notes.pop(idx)
        save(data); t,kb=render_notes(data,0); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("note_edit_"):
        idx=int(d[10:]); ctx.user_data["note_edit_idx"]=idx; ctx.user_data["note_step"]="edit"
        await q.edit_message_text("Введи новый текст заметки:")
    elif d=="note_add":
        ctx.user_data["note_step"]="add"
        await q.edit_message_text("📝 Введи текст заметки:")

    # TABEX
    elif d=="tabex_menu":
        t,kb=render_tabex(data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="tabex_start":
        data["tabex_start"]=today_key(); data["tabex_taken"]={}; save(data)
        t,kb=render_tabex(data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="tabex_took":
        day=tabex_day(data); scheme=TABEX.get(day,[])
        taken=data.setdefault("tabex_taken",{}).setdefault(today_key(),[])
        for t_str in scheme:
            if t_str not in taken: taken.append(t_str); break
        save(data); t,kb=render_tabex(data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="tabex_reset":
        data.pop("tabex_start",None); data.pop("tabex_taken",None); save(data)
        t,kb=render_tabex(data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")

    # EDITOR
    elif d=="editor":
        t,kb=render_editor(); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("ed_blk_"):
        t,kb=render_edit_block(d[7:]); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("ed_f_"):
        parts=d.split("_",3); field=parts[2]; bid=parts[3]
        ctx.user_data["ed_field"]=field; ctx.user_data["ed_bid"]=bid
        fname={"t":"время (ЧЧ:ММ)","n":"название"}[field]
        await q.edit_message_text(f"Введи новое {fname}:")
    elif d.startswith("ed_p_"):
        parts=d.split("_",3); dr=parts[2]; bid=parts[3]
        for b in DEFAULT:
            if b["id"]==bid:
                p=b.get("p",3)
                if dr=="up" and p>1: b["p"]=p-1
                elif dr=="dn" and p<4: b["p"]=p+1
        save(data); t,kb=render_edit_block(bid); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("ed_del_"):
        bid=d[7:]
        for i,b in enumerate(DEFAULT):
            if b["id"]==bid: DEFAULT.pop(i); break
        save(data); t,kb=render_editor(); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="ed_add":
        ctx.user_data["ed_add_step"]="time"
        await q.edit_message_text("Введи время нового блока (ЧЧ:ММ):")

    # TOGGLE
    elif d.startswith("tog_"):
        parts=d.split("_",2)
        if parts[1]=="prog":
            rest=d[9:]; ph_id,idx=rest.rsplit("_",1); key=f"{ph_id}_{idx}"
            data.setdefault("prog",{})[key]=not data["prog"].get(key,False)
            save(data); t,kb=render_phase(ph_id,data)
            await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown",disable_web_page_preview=True)
        elif parts[1]=="hab":
            rest=d[8:]; bits=rest.rsplit("_",1); off=int(bits[1]) if bits[1].lstrip("-").isdigit() else 0
            dc=bits[0].rsplit("_",1); cat=dc[-1]; ds=dc[0]
            data.setdefault("hab",{})[f"{ds}_{cat}"]=not data["hab"].get(f"{ds}_{cat}",False)
            save(data); t,kb=render_habits(data,off); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
        else:
            rest=d[4:]; ds=rest[:10]; rem=rest[11:]
            p2=rem.rsplit("_",1); pg=int(p2[1]) if len(p2)>1 and p2[1].isdigit() else 0; bid=p2[0]
            data.setdefault("days",{}).setdefault(ds,{"checked":{}}).setdefault("checked",{})
            ck=data["days"][ds]["checked"]; ck[bid]=not ck.get(bid,False)
            data.setdefault("hab",{})
            if ck[bid]:
                if bid=="piano": data["hab"][f"{ds}_piano"]=True
                elif bid=="flute": data["hab"][f"{ds}_flute"]=True
                elif bid in("mix","ear","solf","pt","prac","read"): data["hab"][f"{ds}_mix"]=True
                elif bid=="rev": data["hab"][f"{ds}_review"]=True
            save(data); t,kb=render_day(ds,data,pg); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")

    # ADD EVENT
    elif d.startswith("add_evt_"):
        ds=d[8:]; ctx.user_data["evt_ds"]=ds
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("📌 Дела", callback_data=f"evtt_busy_{ds}"),
             InlineKeyboardButton("👤 Личное", callback_data=f"evtt_personal_{ds}")],
            [InlineKeyboardButton("← Назад", callback_data=f"day_{ds}_0")],
        ])
        await q.edit_message_text("Выбери тип события:", reply_markup=kb)
    elif d.startswith("evtt_"):
        p=d.split("_",2); etype=p[1]; ds=p[2]
        ctx.user_data["evt_ds"]=ds; ctx.user_data["evt_type"]=etype; ctx.user_data["evt_step"]="name"
        await q.edit_message_text(
            "Введи название и время:\n\n"
            "Формат: *Название ЧЧ:ММ–ЧЧ:ММ*\n"
            "Пример: `Встреча 14:00–16:00`",
            parse_mode="Markdown")

    elif d=="noop": pass

async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data=load(); text=update.message.text.strip()

    # ADD EVENT
    if ctx.user_data.get("evt_step")=="name":
        ds=ctx.user_data.pop("evt_ds"); etype=ctx.user_data.pop("evt_type"); ctx.user_data.pop("evt_step",None)
        m=re.search(r"(\d{1,2}:\d{2})\s*[–\-]\s*(\d{1,2}:\d{2})",text)
        if m:
            t_from,t_to=m.group(1),m.group(2)
            name=re.sub(r"\d{1,2}:\d{2}\s*[–\-]\s*\d{1,2}:\d{2}","",text).strip()
            evt={"type":etype,"text":name,"t_from":t_from,"t_to":t_to}
        else:
            evt={"type":etype,"text":text}
        data.setdefault("cal",{}).setdefault(ds,[]).append(evt); save(data)
        t,kb=render_day(ds,data,0)
        await update.message.reply_text("✅ Событие добавлено!", parse_mode="Markdown")
        await update.message.reply_text(t,reply_markup=kb,parse_mode="Markdown")
        return

    # FINANCE — шаг 1: название
    if ctx.user_data.get("fin_step")=="name":
        ctx.user_data["fin_name"]=text; ctx.user_data["fin_step"]="cat"
        fin_type=ctx.user_data.get("fin_type")
        cats = EXP_CATS if fin_type=="exp" else INC_CATS
        kb_rows=[[InlineKeyboardButton(c, callback_data=f"fin_cat_{c}")] for c in cats]
        await update.message.reply_text("Выбери категорию:", reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # FINANCE — шаг 3: сумма
    if ctx.user_data.get("fin_step")=="amount":
        try:
            amount=float(re.sub(r"[^\d.]","",text))
            entry={
                "type": ctx.user_data.pop("fin_type"),
                "name": ctx.user_data.pop("fin_name"),
                "cat":  ctx.user_data.pop("fin_cat"),
                "amount": amount,
                "date": today_key(),
            }
            ctx.user_data.pop("fin_step",None)
            data.setdefault("finance",[]).append(entry); save(data)
            sign="📉 Расход" if entry["type"]=="exp" else "📈 Доход"
            await update.message.reply_text(
                f"✅ {sign} добавлен!\n{entry['cat']}: {entry['name']} — {amount:,.0f} ₸",
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰 Финансы", callback_data="finance")]]))
        except:
            await update.message.reply_text("Введи сумму числом, например: 3500")
        return

    # NOTES — добавить
    if ctx.user_data.get("note_step")=="add":
        ctx.user_data.pop("note_step",None)
        data.setdefault("notes",[]).append({"text":text,"date":today_key()}); save(data)
        t,kb=render_notes(data,0)
        await update.message.reply_text("✅ Заметка добавлена!"); await update.message.reply_text(t,reply_markup=kb,parse_mode="Markdown")
        return

    # NOTES — редактировать
    if ctx.user_data.get("note_step")=="edit":
        idx=ctx.user_data.pop("note_edit_idx"); ctx.user_data.pop("note_step",None)
        notes=data.get("notes",[])
        if idx<len(notes): notes[idx]["text"]=text; notes[idx]["date"]=today_key()
        save(data); t,kb=render_notes(data,0)
        await update.message.reply_text("✅ Заметка обновлена!"); await update.message.reply_text(t,reply_markup=kb,parse_mode="Markdown")
        return

    # EDITOR — поле
    if ctx.user_data.get("ed_field") and ctx.user_data.get("ed_bid"):
        field=ctx.user_data.pop("ed_field"); bid=ctx.user_data.pop("ed_bid")
        if field=="t" and not re.match(r"^\d{1,2}:\d{2}$",text):
            await update.message.reply_text("Неверный формат. Введи ЧЧ:ММ:")
            ctx.user_data["ed_field"]=field; ctx.user_data["ed_bid"]=bid; return
        for b in DEFAULT:
            if b["id"]==bid: b[field]=text
        if field=="t": DEFAULT.sort(key=lambda b: tmin(b["t"]))
        save(data); await update.message.reply_text("✅ Изменено!")
        t,kb=render_editor(); await update.message.reply_text(t,reply_markup=kb,parse_mode="Markdown")
        return

    # EDITOR — добавить блок
    if ctx.user_data.get("ed_add_step")=="time":
        if re.match(r"^\d{1,2}:\d{2}$",text):
            ctx.user_data["ed_add_t"]=text; ctx.user_data["ed_add_step"]="name"
            await update.message.reply_text("Введи название блока:")
        else:
            await update.message.reply_text("Неверный формат. Введи ЧЧ:ММ:")
        return

    if ctx.user_data.get("ed_add_step")=="name":
        t_str=ctx.user_data.pop("ed_add_t"); ctx.user_data.pop("ed_add_step",None)
        DEFAULT.append({"id":f"c_{t_str.replace(':','')}","t":t_str,"n":text,"d":"","dur":60,"p":3})
        DEFAULT.sort(key=lambda b: tmin(b["t"]))
        save(data); await update.message.reply_text("✅ Блок добавлен!")
        t,kb=render_editor(); await update.message.reply_text(t,reply_markup=kb,parse_mode="Markdown")
        return

    await update.message.reply_text("Используй /start для меню")

# ─── REMINDERS ───────────────────────────────────────────────────────────────

async def send_reminder(ctx):
    try: await ctx.bot.send_message(chat_id=ctx.job.data["cid"],text=ctx.job.data["msg"],parse_mode="Markdown")
    except Exception as e: logger.error(e)

async def check_event_reminders(ctx):
    cid=ctx.job.data["cid"]; data=load()
    now=now_a(); ds=now.strftime("%Y-%m-%d"); cur=now.hour*60+now.minute
    for e in data.get("cal",{}).get(ds,[]):
        if e.get("t_from") and tmin(e["t_from"])-cur==15:
            try: await ctx.bot.send_message(cid,f"⏰ Через 15 мин: *{e['text']}* в {e['t_from']}",parse_mode="Markdown")
            except Exception as ex: logger.error(ex)

async def check_tabex_reminders(ctx):
    cid=ctx.job.data["cid"]; data=load()
    day=tabex_day(data)
    if not day or day>25: return
    scheme=TABEX.get(day,[]); taken=data.get("tabex_taken",{}).get(today_key(),[])
    now=now_a(); cur=now.hour*60+now.minute
    for t_str in scheme:
        if t_str not in taken and tmin(t_str)-cur==10:
            try: await ctx.bot.send_message(cid,f"💊 *Табекс* — через 10 мин приём таблетки ({t_str})",parse_mode="Markdown")
            except Exception as ex: logger.error(ex)

def setup_jobs(app, cid):
    jq=app.job_queue
    for t_str,msg in [
        ("07:25","⏰ *Подъём через 5 минут!*"),
        ("07:30","🌅 *Подъём!*\nВода, умыться, без телефона 20 мин."),
        ("07:50","🍳 *Завтрак + сборы*"),
        ("13:20","🍽 *Обед* — 45 мин, выйди подышать"),
        ("19:00","🔴 *Ревью дня*\n\nЧто сделал:\n\nЧто получилось:\n\nЧто было сложно:\n\nЗавтра:"),
        ("21:00","🌙 *Подготовка ко сну*\nУбери телефон."),
        ("22:00","😴 *Отбой!* Спокойной ночи."),
    ]:
        h,m=map(int,t_str.split(":"))
        jq.run_daily(send_reminder,time=dtime(hour=h,minute=m,tzinfo=TZ),data={"cid":cid,"msg":msg})
    jq.run_repeating(check_event_reminders,interval=60,first=10,data={"cid":cid})
    jq.run_repeating(check_tabex_reminders,interval=60,first=15,data={"cid":cid})

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("myid",myid))
    app.add_handler(CallbackQueryHandler(btn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,msg_handler))
    if CHAT_ID: setup_jobs(app,CHAT_ID); logger.info(f"Jobs → {CHAT_ID}")
    logger.info("Bot started")
    app.run_polling()

if __name__=="__main__": main()
