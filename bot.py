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
        return {"days":{}, "cal":{}, "prog":{}, "hab":{}}

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

# ─── PRIORITIES ──────────────────────────────────────────────────────────────
# P1 = фиксированные (не двигаются)
# P2 = гибкие обязательные (двигаются, не удаляются: обед, ревью, сон)
# P3 = учёба (двигаются в свободные слоты, сокращаются)
# P4 = заполнители (перерывы, свободное время — удаляются если нет места)

DEFAULT = [
    {"id":"wake",  "t":"07:30","n":"Подъём",              "d":"Без телефона — вода, умыться, выглянуть в окно","dur":20, "p":1},
    {"id":"bfast", "t":"07:50","n":"Завтрак + сборы",     "d":"40 мин","dur":40, "p":2},
    {"id":"go",    "t":"08:30","n":"Выезд",               "d":"До часа пик","dur":30, "p":1},
    {"id":"solf",  "t":"09:00","n":"Сольфеджио",          "d":"60 мин — ноты, ритм, интервалы","dur":60, "p":3},
    {"id":"ear",   "t":"10:00","n":"Ear Training",        "d":"30 мин","dur":30, "p":3},
    {"id":"b1",    "t":"10:30","n":"Перерыв",             "d":"10 мин — встать, вода","dur":10, "p":4},
    {"id":"piano", "t":"10:40","n":"Фортепиано",          "d":"60 мин — гаммы, этюд","dur":60, "p":3},
    {"id":"flute", "t":"10:40","n":"Флейта",              "d":"60 мин — долгие ноты, гаммы, этюд","dur":60, "p":3},
    {"id":"b2",    "t":"11:40","n":"Перерыв",             "d":"10 мин","dur":10, "p":4},
    {"id":"pt",    "t":"11:50","n":"Pro Tools",           "d":"90 мин — по курсу Udemy","dur":90, "p":3},
    {"id":"lunch", "t":"13:20","n":"Обед + пауза",        "d":"45 мин — выйти подышать","dur":45, "p":2},
    {"id":"prac",  "t":"14:05","n":"Практика",            "d":"2 ч — применение изученного","dur":120, "p":3},
    {"id":"b3",    "t":"16:05","n":"Перерыв",             "d":"15 мин","dur":15, "p":4},
    {"id":"read",  "t":"16:20","n":"Чтение / теория",     "d":"60 мин — книги, статьи, документация","dur":60, "p":3},
    {"id":"sport", "t":"17:20","n":"Прогулка / спорт",    "d":"45 мин","dur":45, "p":2},
    {"id":"free",  "t":"18:05","n":"Свободное время",     "d":"Личные дела, отдых","dur":55, "p":4},
    {"id":"rev",   "t":"19:00","n":"Ревью дня",           "d":"5 мин — записать в заметки","dur":10, "p":2},
    {"id":"wind",  "t":"21:00","n":"Подготовка ко сну",   "d":"Убрать телефон, приглушить свет","dur":60, "p":2},
    {"id":"slp",   "t":"22:00","n":"Отбой",               "d":"Цель — до 22:00","dur":0, "p":1},
]

LATEST_ALLOWED = {
    "lunch": 14*60,   # обед не позже 14:00
    "rev":   22*60,   # ревью не позже 22:00
    "wind":  22*60,   # подготовка ко сну не позже 22:00
    "slp":   23*60,   # отбой не позже 23:00
}

def build_schedule(date_str, data):
    dow = datetime.strptime(date_str, "%Y-%m-%d").weekday()  # 0=пн, 6=вс

    # Воскресенье — отдых
    if dow == 6:
        base = [b.copy() for b in DEFAULT if b["id"] in ("wake","bfast","go","lunch","sport","free","rev","wind","slp")]
        for b in base:
            if b["id"] == "free": b["d"] = "Полный отдых 🌿"; b["dur"] = 170
        evts = data.get("cal",{}).get(date_str,[])
        return sorted(base, key=lambda x: tmin(x["t"]))

    # Суббота — только PT + Ear Training
    if dow == 5:
        skip = {"piano","flute","solf","b1"}
        base = [b.copy() for b in DEFAULT if b["id"] not in skip]

    # Вт/Чт — Сольфеджио + Флейта + Ear Training + PT
    elif dow in (1, 3):
        skip = {"piano"}
        base = [b.copy() for b in DEFAULT if b["id"] not in skip]

    # Пн/Ср/Пт — Сольфеджио + Фортепиано + Ear Training + PT
    else:
        skip = {"flute"}
        base = [b.copy() for b in DEFAULT if b["id"] not in skip]

    evts = data.get("cal",{}).get(date_str,[])

    # Собираем фиксированные события (P1) из cal
    fixed_events = []
    for e in evts:
        if e.get("t_from") and e.get("t_to"):
            fixed_events.append({
                "id": "evt_"+re.sub(r"\W","_",e["text"])[:12].lower(),
                "t": e["t_from"],
                "n": e["text"],
                "d": f"до {e['t_to']}",
                "dur": tmin(e["t_to"]) - tmin(e["t_from"]),
                "p": 1,
                "t_end": tmin(e["t_to"]),
                "_evt": True
            })

    # Для каждого фиксированного события применяем логику сдвига
    for fe in fixed_events:
        fe_start = tmin(fe["t"])
        fe_end = fe["t_end"]
        new_base = []
        p3_queue = []  # учёба для переноса после события

        for b in base:
            bstart = tmin(b["t"])
            bend = bstart + b.get("dur", 30)
            p = b.get("p", 3)

            if b.get("_evt"):
                new_base.append(b)
                continue

            # Блок полностью внутри события
            if bstart >= fe_start and bend <= fe_end:
                if p == 1:
                    new_base.append(b)  # P1 остаётся (например подъём не может быть внутри)
                elif p == 2:
                    # Обед внутри работы — оставляем если это логично (обеденное время)
                    if b["id"] == "lunch" and fe_start <= bstart <= fe_start + 240:
                        new_base.append(b)
                    else:
                        # Сдвигаем после события
                        b = b.copy()
                        b["t"] = mtime(fe_end)
                        new_base.append(b)
                elif p == 3:
                    p3_queue.append(b)  # учёба — переносим после события
                elif p == 4:
                    pass  # перерывы внутри события — удаляем

            # Блок частично пересекается
            elif bstart < fe_end and bend > fe_start:
                if p == 1:
                    new_base.append(b)
                elif p in (2, 3):
                    b = b.copy()
                    b["t"] = mtime(fe_end)
                    new_base.append(b) if p == 2 else p3_queue.append(b)
                elif p == 4:
                    pass
            else:
                new_base.append(b)

        # Вставляем учёбу после события в свободные слоты
        cursor = fe_end
        for b in sorted(p3_queue, key=lambda x: x.get("p",3)):
            # Проверяем не слишком ли поздно
            max_allowed = 22 * 60  # по умолчанию не позже 22:00
            if cursor + b["dur"] <= max_allowed:
                b = b.copy()
                b["t"] = mtime(cursor)
                cursor += b["dur"] + 10  # +10 мин перерыв
                new_base.append(b)
            # Если поздно — пропускаем P3, P2 сохраняем сжатыми

        new_base.append(fe)
        base = sorted(new_base, key=lambda x: tmin(x["t"]))

    # Финальная проверка: P2 блоки не позже лимита
    result = []
    for b in base:
        limit = LATEST_ALLOWED.get(b["id"])
        if limit and tmin(b["t"]) > limit:
            b = b.copy()
            b["t"] = mtime(limit)
        result.append(b)

    return sorted(result, key=lambda x: tmin(x["t"]))

# ─── PHASES ──────────────────────────────────────────────────────────────────

PHASES = [
    # СОЛЬФЕДЖИО
    {"id":"sl1","cat":"🟣 Сольфеджио","w":"1–4","title":"Ноты и ритм",
     "tasks":[
         "Линейки скрипичного ключа: Ми-Соль-Си-Ре-Фа\n→ мнемоника: «Мама Гоши Сделала Рисовую Фигуру»",
         "Промежутки: Фа-Ля-До-Ми",
         "Ритм: целая=4, половинная=2, четверть=1, восьмая=0.5\n→ отстукивай по колену под метроном",
         "Петь мелодию по нотам: сначала с фортепиано, потом без",
     ],
     "links":[
         ("📖 Уроки теории","https://www.musictheory.net/lessons"),
         ("🎯 Тренажёр нот","https://www.musictheory.net/exercises/note"),
         ("🎥 Нотная грамота за 12 мин (YouTube)","https://www.youtube.com/watch?v=ZN41d7Txbx8"),
     ]},
    {"id":"sl2","cat":"🟣 Сольфеджио","w":"5–10","title":"Интервалы и пение","req":"sl1",
     "tasks":[
         "Петь гамму До мажор по нотам — с фортепиано и без",
         "Диктант: найди первую ноту на фортепиано → запиши → дальше по слуху",
         "Интонировать интервалы: терция, квинта, октава",
     ],
     "links":[
         ("🎯 Тренажёр нот","https://www.musictheory.net/exercises/note"),
     ]},
    {"id":"sl3","cat":"🟣 Сольфеджио","w":"11–20","title":"Тональности","req":"sl2",
     "tasks":[
         "Диезы: Фа-До-Соль-Ре-Ля-Ми-Си. Бемоли: обратно\n→ 1 диез=Соль, 2=Ре, 3=Ля мажор",
         "Хроматическая гамма — петь и записывать",
         "Транспозиция: перепиши Менуэт из До в Соль мажор (+квинта на каждую ноту)",
     ],
     "links":[]},

    # EAR TRAINING
    {"id":"et1","cat":"🟣 Ear Training","w":"1–4","title":"Интервалы","req":"sl1",
     "tasks":[
         "Ассоциации интервалов:\n→ малая терция = Подмосковные вечера\n→ квинта = Star Wars\n→ октава = Somewhere Over the Rainbow",
         "Тренажёр интервалов — 20 мин в день, записывай % угадывания",
         "Петь интервалы от любой ноты вверх и вниз",
         "Цель: уверенно различать приму/терцию/квинту/октаву",
     ],
     "links":[
         ("🎯 Ear interval тренажёр","https://www.musictheory.net/exercises/ear-interval"),
     ]},
    {"id":"et2","cat":"🟣 Ear Training","w":"5–8","title":"Аккорды и лады","req":"et1",
     "tasks":[
         "Мажор=радостно, минор=грустно, G7=напряжённо\n→ 10–15 аккордов за сессию",
         "Анализ трека: тональность + первые 4 аккорда",
         "Записывай % угадывания каждую сессию",
     ],
     "links":[
         ("🎯 Ear chord тренажёр","https://www.musictheory.net/exercises/ear-chord"),
     ]},
    {"id":"et3","cat":"🟣 Ear Training","w":"9–16","title":"Тембр и частоты","req":"et2",
     "tasks":[
         "Карта частот:\n→ 100 Гц = бум\n→ 200–400 = каша\n→ 1–3 кГц = присутствие\n→ 5–8 кГц = резкость\n→ 10+ кГц = воздух",
         "Quiztones — угадывать частоту, 30 мин в день",
         "Слышать компрессию без плагина: барабаны + ratio 10:1, bypass туда-сюда",
     ],
     "links":[
         ("🎯 Quiztones","https://www.quiztones.com"),
     ]},

    # ФОРТЕПИАНО
    {"id":"pn1","cat":"🔵 Фортепиано","w":"1–4","title":"Постановка рук","req":"sl1",
     "tasks":[
         "Разогрев 5 мин:\n→ сжимай пальцы от мизинца к указательному\n→ вращай запястья по 10 раз",
         "До-Ре-Ми-Фа-Соль каждой рукой:\n→ большой палец на До (C4)\n→ медленно, с весом, каждый палец опускается",
         "Бах Менуэт BWV Anh.114:\n→ по 2 такта: правая → левая → вместе\n→ не переходи дальше пока не звучит уверенно",
     ],
     "links":[
         ("🎼 Ноты Менуэта (IMSLP)","https://imslp.org/wiki/Minuet_in_G_major,_BWV_Anh.114_(Bach,_Johann_Sebastian)"),
         ("🎥 Разбор Менуэта Баха","https://www.youtube.com/watch?v=pDOCBTJMQLk"),
     ]},
    {"id":"pn2","cat":"🔵 Фортепиано","w":"5–10","title":"Гаммы + аккорды","req":"pn1",
     "tasks":[
         "Гамма До мажор двумя руками 2 октавы:\n→ аппликатура 1-2-3/1-2-3-4-5\n→ метроном 60 bpm",
         "Трезвучия До–Фа–Соль с левым басом",
         "По 4 такта с метрономом: правая → левая → вместе",
     ],
     "links":[
         ("🎼 Ноты Менуэта (IMSLP)","https://imslp.org/wiki/Minuet_in_G_major,_BWV_Anh.114_(Bach,_Johann_Sebastian)"),
     ]},
    {"id":"pn3","cat":"🔵 Фортепиано","w":"11–20","title":"Джаз","req":"pn2",
     "tasks":[
         "Гаммы Соль (Фа#) и Ре (Фа#, До#) — 2 октавы, 60–80 bpm",
         "Септаккорды:\n→ Cmaj7: До-Ми-Соль-Си\n→ Dm7: Ре-Фа-Ля-До\n→ G7: Соль-Си-Ре-Фа\n→ G7 «хочет» разрешиться в Cmaj7",
         "Autumn Leaves: только аккорды левой рукой, один в 2–4 счёта",
     ],
     "links":[
         ("🎼 Autumn Leaves ноты","https://www.musicnotes.com/sheetmusic/mtd.asp?ppn=MN0063367"),
         ("🎥 Autumn Leaves для начинающих","https://www.youtube.com/watch?v=RMrBMFVwdSE"),
     ]},

    # ФЛЕЙТА
    {"id":"fl1","cat":"🔵 Флейта","w":"1–2","title":"Возобновление","req":"sl1",
     "tasks":[
         "Долгие ноты Ля/Си/До:\n→ один вдох, ровно, без вибрато\n→ по 3–4 раза каждую",
         "Гамма До мажор C4–C5, 50–60 bpm",
         "Простая мелодия наизусть + запись на телефон",
     ],
     "links":[]},
    {"id":"fl2","cat":"🔵 Флейта","w":"3–8","title":"Техника","req":"fl1",
     "tasks":[
         "Разогрев: хроматически вверх До→До#→Ре... до Соль второй октавы, каждую 4–8 счётов",
         "Гаммы До C4–C6, Соль G4–G6, Ре D4–D6 + арпеджио плавно",
         "Этюд с метрономом. Раз в неделю — запись на телефон",
     ],
     "links":[
         ("🎼 Андерсен op.33 (IMSLP)","https://imslp.org/wiki/24_Etudes,_Op.33_(Andersen,_Joachim)"),
     ]},

    # PRO TOOLS — по курсу Udemy "Avid Pro Tools: Beginner to Advanced"
    {"id":"pt1","cat":"🔵 Pro Tools","w":"1–2","title":"Установка и первая сессия",
     "tasks":[
         "Лекция 01 (13 мин): Установка Pro Tools\n→ активация Avid, выбор аудиодрайвера",
         "Лекция 02 (8 мин): Создание сессии\n→ sample rate, bit depth, путь сохранения",
         "Лекция 03 (21 мин): Аудиотреки\n→ создание, именование, запись",
     ],
     "links":[
         ("🎥 Udemy курс Pro Tools","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/"),
         ("📖 Avid документация","https://resources.avid.com/SupportFiles/PT/Pro%20Tools%20Reference%20Guide.pdf"),
     ]},
    {"id":"pt2","cat":"🔵 Pro Tools","w":"2–3","title":"Режимы редактирования и Fades",
     "tasks":[
         "Лекция 04 (25 мин): Edit Modes и Fades\n→ Shuffle / Slip / Spot / Grid\n→ Smart Tool = F6\n→ Command+= Edit↔Mix",
         "Лекция 18 (6 мин): Clip Gain vs Volume Automation\n→ Clip Gain = до фейдера (треугольник на клипе)\n→ Volume Automation = после фейдера",
         "Лекция 19 (11 мин): Edit Modes Recap\n→ Relative Grid Mode",
         "Шорткаты: R=запись, B=разрезать, Option+клик=bypass",
     ],
     "links":[
         ("🎥 Udemy курс Pro Tools","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/"),
     ]},
    {"id":"pt3","cat":"🔵 Pro Tools","w":"3–4","title":"MIDI, EQ и Inserts",
     "tasks":[
         "Лекция 05 (28 мин): MIDI ноты и Quantize\n→ Piano Roll, квантизация",
         "Лекция 06 (14 мин): Inserts и EQ плагин\n→ EQ3 7-Band: HPF, Low/Mid/High shelf",
         "Практика: HPF на каждом треке\n→ вокал 80–100 Гц, гитара 100–120, клавиши 120–150",
     ],
     "links":[
         ("🎥 Udemy курс Pro Tools","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/"),
     ]},
    {"id":"pt4","cat":"🔵 Pro Tools","w":"4–5","title":"Эффекты, Sends и Busses",
     "tasks":[
         "Лекция 07 (30 мин): Effects, Sends и Busses\n→ Aux треки, шины, параллельная обработка",
         "Лекция 11 (9 мин): Pre vs Post Fader Sends\n→ Pre Fader = не зависит от фейдера\n→ Post Fader = зависит",
         "Лекция 08 (22 мин): Printing to Audio Track\n→ запись обработанного сигнала",
     ],
     "links":[
         ("🎥 Udemy курс Pro Tools","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/"),
     ]},
    {"id":"pt5","cat":"🔵 Pro Tools","w":"5–6","title":"Автоматизация и запись",
     "tasks":[
         "Лекция 13 (9 мин): Volume Automation\n→ режимы Write/Touch/Latch/Read",
         "Лекция 14 (5 мин): More on Automation",
         "Лекция 17 (25 мин): Playlists для записи нескольких дублей",
         "Лекция 16 (5 мин): Запись гитарной партии",
     ],
     "links":[
         ("🎥 Udemy курс Pro Tools","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/"),
     ]},
    {"id":"pt6","cat":"🔵 Pro Tools","w":"6–7","title":"Организация и импорт",
     "tasks":[
         "Лекция 21 (9 мин): Backup сессии",
         "Лекция 23 (7 мин): Импорт аудио",
         "Лекция 24 (12 мин): Именование и цветовое кодирование треков\n→ 01_Kick, 02_Snare, 10_Bass, 20_Vox",
         "Лекция 25 (14 мин): Auxiliary Tracks и Routing Folders",
     ],
     "links":[
         ("🎥 Udemy курс Pro Tools","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/"),
     ]},
    {"id":"pt7","cat":"🔵 Pro Tools","w":"7–8","title":"Сведение: EQ и баланс",
     "tasks":[
         "Лекция 26 (17 мин): Editing and Balancing\n→ грубый баланс без плагинов — только фейдеры и пан",
         "Лекция Reverb and Delay (24 мин): реверб и дилей\n→ умеренно, через Aux",
         "Лекция Delay and Compression (23 мин): компрессия\n→ Dyn3: ratio 4:1, attack 10мс, GR 3–6 dB",
     ],
     "links":[
         ("🎥 Udemy курс Pro Tools","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/"),
     ]},
    {"id":"pt8","cat":"🔵 Pro Tools","w":"8–9","title":"Сведение: динамика и мастеринг",
     "tasks":[
         "Лекция Sends Automation (17 мин): автоматизация отправок",
         "Лекция Loudness Units (11 мин): LUFS, true peak\n→ стриминг: -14 LUFS, -1 dBTP",
         "Лекция Bouncing a Mix (12 мин): финальный баунс\n→ форматы, настройки",
         "Практика: тест на телефоне, наушниках, мониторах",
     ],
     "links":[
         ("🎥 Udemy курс Pro Tools","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/"),
     ]},
    {"id":"pt9","cat":"🔵 Pro Tools","w":"9–10","title":"Продвинутые инструменты",
     "tasks":[
         "Лекция Consolidate & Clip Grouping (6 мин)",
         "Лекция AudioSuite (4 мин): оффлайн-обработка",
         "Лекция Tab to Transients (3 мин)",
         "Лекция Strip Silence (6 мин)",
         "Лекция Batch Rename (7 мин)",
         "Лекция Import Session Data (4 мин)",
         "Лекция Saving a Session Template (3 мин): создание шаблона",
     ],
     "links":[
         ("🎥 Udemy курс Pro Tools","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/"),
     ]},
    {"id":"pt10","cat":"🔵 Pro Tools","w":"11+","title":"Реальные проекты",
     "tasks":[
         "Протокол 8 шагов на каждый проект:\n1. PT + шаблон\n2. Референс того же жанра\n3. Грубый баланс без плагинов\n4. HPF + срез резонансов\n5. Dyn3 + параллельная компрессия\n6. Реверб/дилей умеренно\n7. Мониторы → наушники → телефон\n8. Пауза 15 мин — свежим ухом",
         "Лекция Mixing, Reverb, EQ, Compression (33 мин): полный цикл сведения",
         "Лекция Signal Chain Recap (8 мин): порядок обработки",
     ],
     "links":[
         ("🎥 Udemy курс Pro Tools","https://www.udemy.com/course/avid-pro-tools-beginner-to-advanced/"),
     ]},
]

def unlocked(ph, prog):
    req = ph.get("req")
    if not req: return True
    r = next((p for p in PHASES if p["id"]==req), None)
    return r and all(prog.get(f"{r['id']}_{i}") for i in range(len(r["tasks"])))

# ─── МЕНЮ ────────────────────────────────────────────────────────────────────

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Сегодня", callback_data="today"),
         InlineKeyboardButton("📅 Завтра",  callback_data="tomorrow")],
        [InlineKeyboardButton("🗓 Календарь", callback_data="cal_menu"),
         InlineKeyboardButton("📖 Методичка", callback_data="method")],
        [InlineKeyboardButton("🔥 Привычки", callback_data="habits_0"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("✏️ Редактор", callback_data="editor"),
         InlineKeyboardButton("📋 Памятка", callback_data="guide")],
        [InlineKeyboardButton("😴 Сон и фокус", callback_data="sleep_tips")],
    ])

# ─── DAY VIEW ────────────────────────────────────────────────────────────────

def render_day(ds, data, pg=0):
    blocks = build_schedule(ds, data)
    evts = data.get("cal",{}).get(ds,[])
    checked = data.get("days",{}).get(ds,{}).get("checked",{})
    done = sum(1 for b in blocks if checked.get(b["id"]))
    pct = round(done/len(blocks)*100) if blocks else 0
    bar = "█"*(pct//10)+"░"*(10-pct//10)

    dow = datetime.strptime(ds, "%Y-%m-%d").weekday()
    rot = ["Пн: Сольф+Форте+Слух+PT","Вт: Сольф+Флейта+Слух+PT","Ср: Сольф+Форте+Слух+PT","Чт: Сольф+Флейта+Слух+PT","Пт: Сольф+Форте+Слух+PT","Сб: PT+Слух","Вс: Отдых 🌿"][dow]
    lines = [f"*{day_label(ds)}*", f"_{rot}_"]
    for e in evts:
        icon = {"busy":"📌","personal":"👤","orch":"🎼","live":"🎤"}.get(e.get("type"),"•")
        tr = f" {e['t_from']}–{e['t_to']}" if e.get("t_from") else ""
        lines.append(f"{icon} {e.get('text','')}{tr}")
    lines.append(f"\n{bar} {pct}% ({done}/{len(blocks)})\n{'─'*28}")

    per=8; total=(len(blocks)+per-1)//per
    pg=max(0,min(pg,total-1))
    visible=blocks[pg*per:(pg+1)*per]

    kb=[]
    for b in visible:
        ck=checked.get(b["id"],False)
        label=f"{'✅' if ck else '⬜'} {b['t']} {b['n']}"
        kb.append([InlineKeyboardButton(label, callback_data=f"tog_{ds}_{b['id']}_{pg}")])

    nav=[]
    if pg>0: nav.append(InlineKeyboardButton("◀", callback_data=f"day_{ds}_{pg-1}"))
    if pg<total-1: nav.append(InlineKeyboardButton("▶", callback_data=f"day_{ds}_{pg+1}"))
    if nav: kb.append(nav)

    kb.append([InlineKeyboardButton("➕ Добавить событие", callback_data=f"add_evt_{ds}")])
    kb.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)

# ─── GUIDE (ПАМЯТКА) ─────────────────────────────────────────────────────────

GUIDE_TEXT = """*📋 Памятка по категориям расписания*

🔴 *P1 — Фиксированные* (не двигаются никогда)
→ Подъём, отбой, работа, оркестр, важные встречи
→ Всё остальное строится вокруг них

🟡 *P2 — Гибкие обязательные* (двигаются, не удаляются)
→ Завтрак, обед, ревью дня, подготовка ко сну
→ Обед внутри работы — остаётся (логично)
→ Имеют лимит: обед не позже 14:00, отбой не позже 23:00

🟢 *P3 — Учёба* (переносятся в свободные слоты)
→ Сольфеджио, фортепиано, флейта, ear training, микс
→ Если слот занят — переносятся после события
→ Если после события слишком поздно — пропускаются на этот день

⚪ *P4 — Заполнители* (удаляются если нет места)
→ Перерывы, свободное время
→ Внутри рабочего блока — убираются автоматически

─────────────────────────
*Как добавить событие:*
Нажми ➕ в расписании → выбери тип → напиши:
`Название 14:00–16:00`

Расписание само сдвинется под твой промежуток.
─────────────────────────
*Совет дня:*
Максимум 2 учебных блока в день — один Pro Tools, один инструмент. Качество важнее количества."""

# ─── SLEEP TIPS ──────────────────────────────────────────────────────────────

SLEEP_TEXT = """*😴 Сон и фокус — практическое руководство*

*Проблема:* поздний подъём, сложно заснуть, нет энергии днём.

─────────────────────────
*🌅 Утро — первые 30 минут*

1. Подъём в одно время даже в выходные — это главное
2. Сразу вода — 1–2 стакана (тело обезвожено после сна)
3. Телефон — только через 20 мин после подъёма
4. Свет: открой шторы или выйди на балкон — запускает циркадный ритм
5. Не проверяй соцсети пока не позавтракал

*Почему:* первые 30 мин задают тон всему дню. Телефон сразу = тревожность и рассеянность.

─────────────────────────
*☀️ День — поддержание фокуса*

• Правило 25+5: работай 25 мин, перерыв 5 мин (Pomodoro)
• Перерыв = встать, пройтись, вода. Не телефон
• Кофе — не раньше 09:30 (не сразу после подъёма — кортизол и так высокий)
• Кофе — не позже 15:00 (иначе мешает сну)
• Обед без экрана хотя бы 15 мин

─────────────────────────
*🌙 Вечер — подготовка ко сну*

• За 1 час до сна: приглуши свет (телефон на min яркость)
• Телефон убираем в 21:00 — ревью записываешь в блокнот или диктуешь
• Не ешь за 2 часа до сна
• Температура в комнате 18–20°C — идеально для сна
• Если не можешь заснуть: дыхание 4-7-8 (вдох 4 сек, задержка 7, выдох 8)

─────────────────────────
*📱 Телефон и мозг*

Синий свет экрана подавляет мелатонин на 2–3 часа.
Соцсети перед сном = мозг получает дофамин и не может успокоиться.

Решение: Night mode + автояркость с 20:00.
Идеально: телефон за дверью спальни.

─────────────────────────
*⚡ Если сбился режим*

Не отсыпайся до обеда — это сдвигает цикл ещё дальше.
Встань в запланированное время (даже если поздно лёг).
Один-два дня — и ритм восстановится.

─────────────────────────
*📈 Твой план:*
→ Подъём 07:30 — без исключений
→ Отбой 22:00 — телефон убран в 21:00
→ Через 2 недели стабильного режима станет значительно легче"""

# ─── METHOD ──────────────────────────────────────────────────────────────────

def render_method(data):
    prog = data.get("prog",{})
    cats = list(dict.fromkeys(p["cat"] for p in PHASES))
    kb=[]
    for cat in cats:
        kb.append([InlineKeyboardButton(f"── {cat} ──", callback_data="noop")])
        for ph in PHASES:
            if ph["cat"]!=cat: continue
            ul=unlocked(ph,prog)
            tot=len(ph["tasks"])
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
        first_line=task.split("\n")[0]
        short=first_line[:48]+"…" if len(first_line)>48 else first_line
        kb.append([InlineKeyboardButton(f"{'✅' if done else '⬜'} {short}", callback_data=f"tog_prog_{pid}_{i}")])
    kb.append([InlineKeyboardButton("← Методичка", callback_data="method")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)

# ─── HABITS ──────────────────────────────────────────────────────────────────

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

# ─── STATS ───────────────────────────────────────────────────────────────────

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

# ─── CALENDAR ────────────────────────────────────────────────────────────────

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

# ─── EDITOR ──────────────────────────────────────────────────────────────────

def render_editor():
    kb=[]
    for b in DEFAULT:
        p_icon=["","🔴","🟡","🟢","⚪"][b.get("p",3)]
        kb.append([InlineKeyboardButton(f"{p_icon} {b['t']} — {b['n']}", callback_data=f"ed_blk_{b['id']}")])
    kb.append([InlineKeyboardButton("➕ Добавить блок", callback_data="ed_add")])
    kb.append([InlineKeyboardButton("← Меню", callback_data="menu")])
    return "*✏️ Редактор расписания*\nНажми на блок:", InlineKeyboardMarkup(kb)

def render_edit_block(bid):
    b=next((x for x in DEFAULT if x["id"]==bid),None)
    if not b: return "Не найдено", InlineKeyboardMarkup([[InlineKeyboardButton("←", callback_data="editor")]])
    p_names={1:"🔴 Фиксированный",2:"🟡 Гибкий обязательный",3:"🟢 Учёба",4:"⚪ Заполнитель"}
    text=f"*{b['t']} — {b['n']}*\n{b['d']}\nПриоритет: {p_names.get(b.get('p',3),'?')}\nЧто изменить?"
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 Время", callback_data=f"ed_f_t_{bid}"),
         InlineKeyboardButton("📝 Название", callback_data=f"ed_f_n_{bid}")],
        [InlineKeyboardButton("⬆️ Приоритет выше", callback_data=f"ed_p_up_{bid}"),
         InlineKeyboardButton("⬇️ Приоритет ниже", callback_data=f"ed_p_dn_{bid}")],
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

    # EDITOR
    elif d=="editor":
        t,kb=render_editor(); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("ed_blk_"):
        t,kb=render_edit_block(d[7:]); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("ed_f_"):
        parts=d.split("_",3); field=parts[2]; bid=parts[3]
        ctx.user_data["ed_field"]=field; ctx.user_data["ed_bid"]=bid
        fname={"t":"время (ЧЧ:ММ)","n":"название","d":"описание"}[field]
        await q.edit_message_text(f"Введи новое {fname}:")
    elif d.startswith("ed_p_"):
        parts=d.split("_",3); direction=parts[2]; bid=parts[3]
        for b in DEFAULT:
            if b["id"]==bid:
                p=b.get("p",3)
                if direction=="up" and p>1: b["p"]=p-1
                elif direction=="dn" and p<4: b["p"]=p+1
        save(data)
        t,kb=render_edit_block(bid); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d.startswith("ed_del_"):
        bid=d[7:]
        for i,b in enumerate(DEFAULT):
            if b["id"]==bid: DEFAULT.pop(i); break
        save(data)
        t,kb=render_editor(); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    elif d=="ed_add":
        ctx.user_data["ed_add_step"]="time"
        await q.edit_message_text("Введи время нового блока (ЧЧ:ММ):")

    # TOGGLE
    elif d.startswith("tog_"):
        parts=d.split("_",2)
        if parts[1]=="prog":
            rest=d[9:]; ph_id,idx=rest.rsplit("_",1); key=f"{ph_id}_{idx}"
            data.setdefault("prog",{})[key]=not data["prog"].get(key,False)
            save(data)
            t,kb=render_phase(ph_id,data); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown",disable_web_page_preview=True)
        elif parts[1]=="hab":
            rest=d[8:]; bits=rest.rsplit("_",1); off=int(bits[1]) if bits[1].lstrip("-").isdigit() else 0
            dc=bits[0].rsplit("_",1); cat=dc[-1]; ds=dc[0]
            data.setdefault("hab",{})[f"{ds}_{cat}"]=not data["hab"].get(f"{ds}_{cat}",False)
            save(data)
            t,kb=render_habits(data,off); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
        else:
            rest=d[4:]; ds=rest[:10]; rem=rest[11:]
            p2=rem.rsplit("_",1); pg=int(p2[1]) if len(p2)>1 and p2[1].isdigit() else 0; bid=p2[0]
            data.setdefault("days",{}).setdefault(ds,{"checked":{}}).setdefault("checked",{})
            ck=data["days"][ds]["checked"]; ck[bid]=not ck.get(bid,False)
            data.setdefault("hab",{})
            if ck[bid]:
                if bid=="piano": data["hab"][f"{ds}_piano"]=True
                elif bid=="flute": data["hab"][f"{ds}_flute"]=True
                elif bid in("mix","ear","solf"): data["hab"][f"{ds}_mix"]=True
                elif bid=="rev": data["hab"][f"{ds}_review"]=True
            save(data)
            t,kb=render_day(ds,data,pg); await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")

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
            "Введи название и время события:\n\n"
            "Формат: *Название ЧЧ:ММ–ЧЧ:ММ*\n"
            "Пример: `Встреча с врачом 14:00–15:00`\n\n"
            "Расписание автоматически сдвинется по приоритетам.",
            parse_mode="Markdown"
        )
    elif d=="noop": pass

async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data=load(); text=update.message.text.strip()

    if ctx.user_data.get("evt_step")=="name":
        ds=ctx.user_data.pop("evt_ds"); etype=ctx.user_data.pop("evt_type"); ctx.user_data.pop("evt_step",None)
        m=re.search(r"(\d{1,2}:\d{2})\s*[–\-]\s*(\d{1,2}:\d{2})",text)
        if m:
            t_from,t_to=m.group(1),m.group(2)
            name=re.sub(r"\d{1,2}:\d{2}\s*[–\-]\s*\d{1,2}:\d{2}","",text).strip()
            evt={"type":etype,"text":name,"t_from":t_from,"t_to":t_to}
        else:
            evt={"type":etype,"text":text}
        data.setdefault("cal",{}).setdefault(ds,[]).append(evt)
        save(data)
        t,kb=render_day(ds,data,0)
        await update.message.reply_text("✅ Событие добавлено! Расписание пересчитано.", parse_mode="Markdown")
        await update.message.reply_text(t,reply_markup=kb,parse_mode="Markdown")
        return

    if ctx.user_data.get("ed_field") and ctx.user_data.get("ed_bid"):
        field=ctx.user_data.pop("ed_field"); bid=ctx.user_data.pop("ed_bid")
        if field=="t" and not re.match(r"^\d{1,2}:\d{2}$",text):
            await update.message.reply_text("Неверный формат. Введи ЧЧ:ММ:")
            ctx.user_data["ed_field"]=field; ctx.user_data["ed_bid"]=bid; return
        for b in DEFAULT:
            if b["id"]==bid: b[field]=text
        if field=="t": DEFAULT.sort(key=lambda b: tmin(b["t"]))
        save(data)
        await update.message.reply_text("✅ Изменено!")
        t,kb=render_editor(); await update.message.reply_text(t,reply_markup=kb,parse_mode="Markdown")
        return

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
        save(data)
        await update.message.reply_text("✅ Блок добавлен!")
        t,kb=render_editor(); await update.message.reply_text(t,reply_markup=kb,parse_mode="Markdown")
        return

    await update.message.reply_text("Используй /start для меню")

# ─── REMINDERS ───────────────────────────────────────────────────────────────

async def reminder(ctx):
    try: await ctx.bot.send_message(chat_id=ctx.job.data["cid"],text=ctx.job.data["msg"],parse_mode="Markdown")
    except Exception as e: logger.error(e)

async def check_event_reminders(ctx):
    cid = ctx.job.data["cid"]
    data = load()
    now = now_a()
    ds = now.strftime("%Y-%m-%d")
    evts = data.get("cal",{}).get(ds,[])
    current_min = now.hour*60+now.minute
    for e in evts:
        if e.get("t_from") and tmin(e["t_from"])-current_min == 15:
            try:
                await ctx.bot.send_message(cid, f"⏰ Через 15 мин: *{e['text']}* в {e['t_from']}", parse_mode="Markdown")
            except Exception as ex: logger.error(ex)

def setup_reminders(app, cid):
    jq=app.job_queue
    for t_str,msg_text in [
        ("07:25","⏰ *Подъём через 5 минут!*"),
        ("07:30","🌅 *Подъём!*\nВода, умыться, без телефона 20 мин."),
        ("07:50","🍳 *Завтрак + сборы*"),
        ("13:20","🍽 *Обед* — 45 мин, выйди подышать"),
        ("19:00","🔴 *Ревью дня*\n\nЧто сделал:\n\nЧто получилось:\n\nЧто было сложно:\n\nЗавтра:"),
        ("21:00","🌙 *Подготовка ко сну*\nУбери телефон. Приглуши свет."),
        ("22:00","😴 *Отбой!* Спокойной ночи."),
    ]:
        h,m=map(int,t_str.split(":"))
        jq.run_daily(reminder,time=dtime(hour=h,minute=m,tzinfo=TZ),data={"cid":cid,"msg":msg_text})
    jq.run_repeating(check_event_reminders,interval=60,first=10,data={"cid":cid})

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("myid",myid))
    app.add_handler(CallbackQueryHandler(btn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,msg_handler))
    if CHAT_ID: setup_reminders(app,CHAT_ID); logger.info(f"Reminders → {CHAT_ID}")
    logger.info("Bot started")
    app.run_polling()

if __name__=="__main__": main()
