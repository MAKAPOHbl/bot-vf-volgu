import os
import re
import json
import time
import threading
import sqlite3
import schedule
from datetime import datetime, timedelta, date, time as dtime
from dotenv import load_dotenv
import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import logging
LOG_FILE = "bot_errors.log"
MAX_AGE_DAYS = 14
def clean_old_logs():
    if not os.path.exists(LOG_FILE):
        return
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return
        cutoff_date = datetime.now() - timedelta(days=MAX_AGE_DAYS)
        cleaned_lines = []
        removed_count = 0
        for line in lines:
            try:
                date_str = line[:10]  # YYYY-MM-DD
                log_date = datetime.strptime(date_str, "%Y-%m-%d")
                if log_date >= cutoff_date:
                    cleaned_lines.append(line)
                else:
                    removed_count += 1
            except:
                cleaned_lines.append(line) 
        if removed_count > 0:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(cleaned_lines)
            logger.info(f"Очистка лога: удалено {removed_count} записей старше {MAX_AGE_DAYS} дней")
    except Exception as e:
        print(f"Ошибка при очистке bot_errors.log: {e}")
logger = logging.getLogger("VKBot")
logger.setLevel(logging.ERROR)
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(name)s | %(funcName)s:%(lineno)d | %(message)s'
)
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
load_dotenv()
VK_TOKEN = os.getenv("VK_TOKEN")
GROUP_ID = os.getenv("VK_GROUP_ID")
DB_PATH = os.getenv("DB_PATH", "appointments.db")
if not VK_TOKEN:
    raise SystemExit("Ошибка: переменная окружения VK_TOKEN не установлена.")
if not GROUP_ID:
    raise SystemExit("Ошибка: переменная окружения VK_GROUP_ID не установлена.")
GROUP_ID = int(GROUP_ID)
vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)
DB_LOCK = threading.Lock()
RU_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]
RU_WEEKDAYS = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье"
]
# Обновлённый список тем
VALID_TOPICS = [
    "Трудовой спор",
    "Гражданское право",
    "Семейный спор",
    "Жилищное право / ЖКХ",
    "Административное",
    "Социальное обеспечение",
]
BTN_BOOK = "Записаться на приём"
BTN_MY = "Моя запись"
BTN_HELP = "Где можно получить помощь"
BTN_DOCS = "Необходимые документы"
BTN_FAQ = "Часто задаваемые вопросы"
BTN_COUNS = "Кто проводит консультации"
BTN_BACK = "Назад"
BTN_CANCEL = "Отмена"
BTN_CANCEL_BOOK = "Отменить запись"
BTN_OTHER_TOPIC = "Другая тема"  # Новая кнопка для ввода своей темы
BTN_ADMIN_LIST = "Список записей"
BTN_ADMIN_DELETE = "Удалить запись"
BTN_SWITCH_TO_USER = "Перейти в меню пользователя"
BTN_SWITCH_TO_ADMIN = "Перейти в меню администратора"
FAQ_1 = "Какую консультацию можно получить"
FAQ_2 = "Срок подготовки ответа или документа"
FAQ_3 = "Представление интересов в суде"
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn
def init_db():
    with DB_LOCK:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS appointments (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                contact TEXT NOT NULL,
                appointment_time TEXT NOT NULL UNIQUE,
                topic TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reminder_sent INTEGER DEFAULT 0
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS user_state (
                user_id INTEGER PRIMARY KEY,
                step TEXT,
                data TEXT,
                updated_at TEXT
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS menu_mode (
                user_id INTEGER PRIMARY KEY,
                mode TEXT NOT NULL
            )
            '''
        )
        conn.commit()
        conn.close()
    clean_old_appointments()
def get_user_state(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT step, data FROM user_state WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"step": None, "data": {}}
    try:
        data = json.loads(row["data"]) if row["data"] else {}
    except Exception:
        data = {}
    return {"step": row["step"], "data": data}
def set_user_state(user_id: int, step: str, data: dict):
    now = datetime.now().isoformat()
    with DB_LOCK:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "REPLACE INTO user_state (user_id, step, data, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, step, json.dumps(data, ensure_ascii=False), now),
        )
        conn.commit()
        conn.close()
def clear_user_state(user_id: int):
    with DB_LOCK:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM user_state WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
def get_menu_mode(user_id: int) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT mode FROM menu_mode WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row and row["mode"] in ("admin", "user"):
        return row["mode"]
    return "admin" if is_admin(user_id) else "user"
def set_menu_mode(user_id: int, mode: str):
    if mode not in ("admin", "user"):
        return
    with DB_LOCK:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "REPLACE INTO menu_mode (user_id, mode) VALUES (?, ?)",
            (user_id, mode),
        )
        conn.commit()
        conn.close()
def get_user_appointment(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT full_name, contact, appointment_time, topic FROM appointments WHERE user_id = ?",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()
    return tuple(row) if row else None
def get_all_appointments():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, full_name, contact, appointment_time, topic FROM appointments ORDER BY appointment_time"
    )
    rows = cur.fetchall()
    conn.close()
    return rows
def delete_appointment(user_id: int):
    with DB_LOCK:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM appointments WHERE user_id = ?", (user_id,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
    return deleted
def save_appointment_atomic(user_id: int, full_name: str, contact: str, datetime_str: str, topic: str):
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with DB_LOCK:
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT user_id FROM appointments WHERE appointment_time = ?", (datetime_str,))
            row = cur.fetchone()
            if row and row["user_id"] != user_id:
                conn.rollback()
                return False, "slot_taken"
            cur.execute(
                "REPLACE INTO appointments (user_id, full_name, contact, appointment_time, topic, created_at, reminder_sent) VALUES (?, ?, ?, ?, ?, ?, 0)",
                (user_id, full_name, contact, datetime_str, topic, now_iso)
            )
            conn.commit()
            return True, None
        except sqlite3.DatabaseError:
            conn.rollback()
            return False, "db_error"
        finally:
            conn.close()
def is_time_available(dt_str: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM appointments WHERE appointment_time = ?", (dt_str,))
    taken = cur.fetchone() is not None
    conn.close()
    return not taken
def clean_old_appointments():
    with DB_LOCK:
        conn = get_conn()
        cur = conn.cursor()
        yesterday = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
        cur.execute("DELETE FROM appointments WHERE appointment_time < ?", (yesterday,))
        conn.commit()
        conn.close()
def send_reminders():
    with DB_LOCK:
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.now()
        window_start = (now + timedelta(hours=23, minutes=29)).strftime("%Y-%m-%d %H:%M")
        window_end = (now + timedelta(hours=24, minutes=31)).strftime("%Y-%m-%d %H:%M")
        cur.execute("""
            SELECT user_id, full_name, contact, appointment_time, topic, created_at
            FROM appointments
            WHERE reminder_sent = 0
              AND appointment_time BETWEEN ? AND ?
              AND datetime(appointment_time) >= datetime(created_at, '+36 hours')
        """, (window_start, window_end))
        rows = cur.fetchall()
        for row in rows:
            user_id = row["user_id"]
            topic = row["topic"]
            dt = datetime.strptime(row["appointment_time"], "%Y-%m-%d %H:%M")
            formatted_date = f"{dt.day} {RU_MONTHS[dt.month - 1]} {dt.year} г."
            formatted_time = dt.strftime("%H:%M")
            weekday = RU_WEEKDAYS[dt.weekday()].capitalize()
            msg = (
                f"🔔 Напоминание: завтра у вас запись на консультацию!\n\n"
                f"👤 ФИО: {row['full_name']}\n"
                f"💬 Тема: {topic}\n"
                f"📅 Дата: {formatted_date}\n"
                f"⏰ Время: {formatted_time}\n"
                f"🗓 День недели: {weekday}\n"
                f"📍 Адрес: 40 лет Победы, 11, каб. 1.16\n\n"
                f"Пожалуйста, не забудьте прийти. С уважением, ЮК ВФ ВолГУ!"
            )
            try:
                vk.messages.send(
                    user_id=user_id,
                    message=msg,
                    random_id=int(time.time() * 1000000) % 2_147_483_647,
                    from_group=GROUP_ID
                )
                cur.execute("UPDATE appointments SET reminder_sent = 1 WHERE user_id = ?", (user_id,))
            except Exception as e:
                print(f"Ошибка отправки напоминания пользователю {user_id}: {e}")
        conn.commit()
        conn.close()
def format_day_label(d: date):
    weekday = RU_WEEKDAYS[d.weekday()].capitalize()
    return f"{weekday}, {d.day} {RU_MONTHS[d.month - 1]}"
def slots_for_date(d: date):
    slots = []
    now = datetime.now()
    if d.weekday() == 1:  # Вторник
        t = datetime.combine(d, dtime(14, 0))
        last = datetime.combine(d, dtime(17, 30))  # Крайний слот начинается в 17:30
    elif d.weekday() == 5:  # Суббота
        t = datetime.combine(d, dtime(9, 0))
        last = datetime.combine(d, dtime(12, 30))
    else:
        return []
    while t <= last:
        if t > now:
            dt_str = t.strftime("%Y-%m-%d %H:%M")
            if is_time_available(dt_str):
                slots.append(t.strftime("%H:%M"))
        t += timedelta(minutes=30)  # Интервал 30 минут
    return slots
def next_scheduled_dates(n=4):
    today = datetime.now().date()
    dates = []
    day = today
    while len(dates) < n:
        if day.weekday() in (1, 5):
            if day > today:
                dates.append(day)
            else:
                now = datetime.now()
                last = datetime.combine(day, dtime(17, 30)) if day.weekday() == 1 else datetime.combine(day, dtime(12, 30))
                if last > now and slots_for_date(day):
                    dates.append(day)
        day += timedelta(days=1)
    return dates
def kb_main_menu(user_id: int = None):
    kb = VkKeyboard(one_time=False)
    kb.add_button(BTN_BOOK, color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button(BTN_MY, color=VkKeyboardColor.SECONDARY)
    kb.add_line()
    kb.add_button(BTN_HELP, color=VkKeyboardColor.SECONDARY)
    kb.add_button(BTN_DOCS, color=VkKeyboardColor.SECONDARY)
    kb.add_line()
    kb.add_button(BTN_FAQ, color=VkKeyboardColor.SECONDARY)
    kb.add_button(BTN_COUNS, color=VkKeyboardColor.SECONDARY)
    if user_id is not None and is_admin(user_id):
        kb.add_line()
        kb.add_button(BTN_SWITCH_TO_ADMIN, color=VkKeyboardColor.PRIMARY)
    return kb
def kb_admin_menu(user_id: int = None):
    kb = VkKeyboard(one_time=False)
    kb.add_button(BTN_ADMIN_LIST, color=VkKeyboardColor.PRIMARY)
    kb.add_button(BTN_ADMIN_DELETE, color=VkKeyboardColor.NEGATIVE)
    if user_id is not None and is_admin(user_id):
        kb.add_line()
        kb.add_button(BTN_SWITCH_TO_USER, color=VkKeyboardColor.SECONDARY)
    return kb
def kb_cancel_only():
    kb = VkKeyboard(one_time=True)
    kb.add_button(BTN_CANCEL, color=VkKeyboardColor.NEGATIVE)
    return kb
def kb_contact():
    kb = VkKeyboard(one_time=True)
    kb.add_button(BTN_BACK, color=VkKeyboardColor.SECONDARY)
    kb.add_line()
    kb.add_button(BTN_CANCEL, color=VkKeyboardColor.NEGATIVE)
    return kb
def kb_topics():
    kb = VkKeyboard(one_time=False)
    for i, topic in enumerate(VALID_TOPICS):
        kb.add_button(topic, color=VkKeyboardColor.PRIMARY)
        if i % 2 == 1 and i != len(VALID_TOPICS) - 1:
            kb.add_line()
    kb.add_line()
    kb.add_button(BTN_OTHER_TOPIC, color=VkKeyboardColor.SECONDARY)
    kb.add_line()
    kb.add_button(BTN_BACK, color=VkKeyboardColor.SECONDARY)
    kb.add_button(BTN_CANCEL, color=VkKeyboardColor.NEGATIVE)
    return kb
def kb_days(day_choices):
    kb = VkKeyboard(one_time=True)
    for i, (label, _) in enumerate(day_choices):
        kb.add_button(label, color=VkKeyboardColor.PRIMARY)
        if i % 2 == 1 and i != len(day_choices) - 1:
            kb.add_line()
    kb.add_line()
    kb.add_button(BTN_BACK, color=VkKeyboardColor.SECONDARY)
    kb.add_button(BTN_CANCEL, color=VkKeyboardColor.NEGATIVE)
    return kb
def kb_times(times):
    kb = VkKeyboard(one_time=True)
    for i, t in enumerate(times):
        kb.add_button(t, color=VkKeyboardColor.PRIMARY)
        if i % 3 == 2 and i != len(times) - 1:
            kb.add_line()
    kb.add_line()
    kb.add_button(BTN_BACK, color=VkKeyboardColor.SECONDARY)
    kb.add_button(BTN_CANCEL, color=VkKeyboardColor.NEGATIVE)
    return kb
def send(peer_id: int, text: str, keyboard=None):
    params = {
        "peer_id": peer_id,
        "message": text,
        "random_id": int(time.time() * 1000000) % 2_147_483_647,
    }
    if keyboard is not None:
        params["keyboard"] = keyboard.get_keyboard()
    vk.messages.send(**params)
def handle_start(peer_id: int, user_id: int):
    clean_old_appointments()
    mode = get_menu_mode(user_id)
    if mode == "admin" and is_admin(user_id):
        send(peer_id, "Чем я могу быть вам полезен?", kb_admin_menu(user_id))
    else:
        send(peer_id, "Чем я могу быть вам полезен?", kb_main_menu(user_id))
def handle_book_start(peer_id: int, user_id: int):
    clean_old_appointments()
    if get_user_appointment(user_id):
        send(peer_id, "У вас уже есть активная запись. Посмотреть или отменить — через пункт «Моя запись».", kb_main_menu(user_id))
        return
    clear_user_state(user_id)
    set_user_state(user_id, "name", {})
    send(peer_id, "Введите, пожалуйста, ваше ФИО.", kb_cancel_only())
def handle_name(peer_id: int, user_id: int, text: str):
    if text.lower() == BTN_CANCEL.lower():
        clear_user_state(user_id)
        send(peer_id, "Запись отменена.", kb_main_menu(user_id))
        return
    if not validate_name(text):
        send(peer_id, "Пожалуйста, введите корректное ФИО (1–64 символов).", kb_cancel_only())
        return
    state = get_user_state(user_id)
    data = state["data"]
    data["full_name"] = text.strip()
    set_user_state(user_id, "contact", data)
    send(peer_id, "Введите ваш номер телефона или адрес электронной почты для связи:", kb_contact())
def handle_contact(peer_id: int, user_id: int, text: str):
    if text == BTN_BACK:
        clear_user_state(user_id)
        set_user_state(user_id, "name", {})
        send(peer_id, "Введите, пожалуйста, ваше ФИО.", kb_cancel_only())
        return
    if text.lower() == BTN_CANCEL.lower():
        clear_user_state(user_id)
        send(peer_id, "Запись отменена.", kb_main_menu(user_id))
        return
    state = get_user_state(user_id)
    data = state["data"]
    contact = text.strip()
    if not validate_contact(contact):
        send(peer_id, "Неверный формат. Введите корректный телефон или адрес электронной почты.\nПримеры: +79001234567 или user@example.com", kb_contact())
        return
    data["contact"] = contact
    set_user_state(user_id, "choose_topic", data)
    send(peer_id, "Выберите тему обращения:", kb_topics())
def handle_choose_topic(peer_id: int, user_id: int, text: str):
    if text == BTN_BACK:
        state = get_user_state(user_id)
        data = state["data"]
        set_user_state(user_id, "contact", data)
        send(peer_id, "Введите адрес электронной почты для обратной связи:", kb_contact())
        return
    if text.lower() == BTN_CANCEL.lower():
        clear_user_state(user_id)
        send(peer_id, "Запись отменена.", kb_main_menu(user_id))
        return
    if text == BTN_OTHER_TOPIC:
        state = get_user_state(user_id)
        data = state["data"]
        data["awaiting_custom_topic"] = True
        set_user_state(user_id, "custom_topic_input", data)
        kb = VkKeyboard(one_time=True)
        kb.add_button(BTN_BACK, color=VkKeyboardColor.SECONDARY)
        kb.add_button(BTN_CANCEL, color=VkKeyboardColor.NEGATIVE)
        send(peer_id, "Введите вашу тему обращения (1-100 символов):", kb)
        return
    state = get_user_state(user_id)
    if state["step"] == "custom_topic_input":
        topic = text.strip()
        if not topic or len(topic) > 100:
            send(peer_id, "Пожалуйста, введите тему обращения (1-100 символов).", kb_cancel_only())
            return
        data = state["data"]
        data["topic"] = topic
        # Продолжаем к выбору даты
        dates = next_scheduled_dates(4)
        if not dates:
            clear_user_state(user_id)
            send(peer_id, "К сожалению, ближайших дат для записи не найдено.", kb_main_menu(user_id))
            return
        day_choices = [(format_day_label(d), d.strftime("%Y-%m-%d")) for d in dates]
        data["day_choices"] = day_choices
        set_user_state(user_id, "choose_day", data)
        send(peer_id, "Выберите ближайший день приёма:", kb_days(day_choices))
        return
    if text not in VALID_TOPICS:
        send(peer_id, "Пожалуйста, выберите тему из списка или нажмите «Другая тема».", kb_topics())
        return
    state = get_user_state(user_id)
    data = state["data"]
    data["topic"] = text
    dates = next_scheduled_dates(4)
    if not dates:
        clear_user_state(user_id)
        send(peer_id, "К сожалению, ближайших дат для записи не найдено.", kb_main_menu(user_id))
        return
    day_choices = []
    for d in dates:
        day_choices.append((format_day_label(d), d.strftime("%Y-%m-%d")))
    data["day_choices"] = day_choices
    set_user_state(user_id, "choose_day", data)
    send(peer_id, "Выберите ближайший день приёма:", kb_days(day_choices))
def handle_choose_day(peer_id: int, user_id: int, text: str):
    if text == BTN_BACK:
        state = get_user_state(user_id)
        data = state["data"]
        set_user_state(user_id, "choose_topic", data)
        send(peer_id, "Выберите тему обращения:", kb_topics())
        return
    if text.lower() == BTN_CANCEL.lower():
        clear_user_state(user_id)
        send(peer_id, "Запись отменена.", kb_main_menu(user_id))
        return
    state = get_user_state(user_id)
    choices = state["data"].get("day_choices", [])
    matched = None
    for label, iso in choices:
        if label == text:
            matched = iso
            break
    if not matched:
        send(peer_id, "Пожалуйста, выберите день из списка.", kb_days(choices))
        return
    chosen_date = datetime.strptime(matched, "%Y-%m-%d").date()
    free_time_slots = slots_for_date(chosen_date)
    if not free_time_slots:
        clear_user_state(user_id)
        send(peer_id, "К сожалению, для этого дня свободных слотов нет. Выберите другой день.", kb_main_menu(user_id))
        return
    data = state["data"]
    data["chosen_date"] = matched
    data["time_choices"] = free_time_slots
    set_user_state(user_id, "choose_time", data)
    send(peer_id, "Выберите время:", kb_times(free_time_slots))
def handle_choose_time(peer_id: int, user_id: int, text: str):
    if text == BTN_BACK:
        state = get_user_state(user_id)
        data = state["data"]
        set_user_state(user_id, "choose_day", data)
        send(peer_id, "Выберите ближайший день приёма:", kb_days(data.get("day_choices", [])))
        return
    if text.lower() == BTN_CANCEL.lower():
        clear_user_state(user_id)
        send(peer_id, "Запись отменена.", kb_main_menu(user_id))
        return
    state = get_user_state(user_id)
    allowed = state["data"].get("time_choices", [])
    if text not in allowed:
        sample = allowed[:9]
        send(peer_id, "Пожалуйста, выберите время из списка.", kb_times(sample))
        return
    chosen_date = state["data"]["chosen_date"]
    dt_str = f"{chosen_date} {text}"
    full_name = state["data"].get("full_name", "")
    contact = state["data"].get("contact", "")
    topic = state["data"].get("topic", "")
    ok, reason = save_appointment_atomic(user_id, full_name, contact, dt_str, topic)
    if not ok:
        if reason == "slot_taken":
            send(peer_id, "К сожалению, этот слот уже заняли. Начните запись заново.", kb_main_menu(user_id))
        else:
            send(peer_id, "Произошла ошибка при сохранении. Попробуйте снова.", kb_main_menu(user_id))
        clear_user_state(user_id)
        return
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    formatted_date = f"{dt.day} {RU_MONTHS[dt.month - 1]} {dt.year} г."
    formatted_time = dt.strftime("%H:%M")
    weekday = RU_WEEKDAYS[dt.weekday()].capitalize()
    confirm_msg = (
        "✅ Вы успешно записаны на приём!\n\n"
        f"👤 ФИО: {full_name}\n"
        f"📞 Контакт: {contact}\n"
        f"💬 Тема: {topic}\n"
        f"📅 Дата: {formatted_date}\n"
        f"⏰ Время: {formatted_time}\n"
        f"🗓 День недели: {weekday}\n\n"
        "Адрес: 40 лет Победы, 11, каб. 1.16\n"
        "С уважением, ЮК ВФ ВолГУ!"
    )
    notify_admins_about_appointment(user_id, full_name, contact, dt_str, topic)
    clear_user_state(user_id)
    send(peer_id, confirm_msg, kb_main_menu(user_id))
def handle_my_appointment(peer_id: int, user_id: int):
    clean_old_appointments()
    rec = get_user_appointment(user_id)
    if not rec:
        send(peer_id, "У вас нет активной записи.", kb_main_menu(user_id))
        return
    full_name, contact, time_str, topic = rec
    date_part, time_part = time_str.split()
    d_obj = datetime.strptime(date_part, "%Y-%m-%d").date()
    date_label = format_day_label(d_obj)
    kb = VkKeyboard(one_time=False)
    kb.add_button(BTN_CANCEL_BOOK, color=VkKeyboardColor.NEGATIVE)
    kb.add_line()
    kb.add_button(BTN_BACK, color=VkKeyboardColor.SECONDARY)
    send(peer_id, f"📋 Ваша запись:\n\n👤 {full_name}\n📞 {contact}\n💬 {topic}\n📅 {date_label} {time_part}", kb)
def handle_cancel_appointment(peer_id: int, user_id: int):
    rec = get_user_appointment(user_id)
    if not rec:
        send(peer_id, "У вас нет активной записи.", kb_main_menu(user_id))
        return
    full_name, contact, time_str, topic = rec
    delete_appointment(user_id)
    notify_admins_about_cancellation(
        user_id,
        full_name,
        contact,
        time_str,
        topic,
        "Отменено пользователем",
        canceled_by="пользователем"
    )
    send(peer_id, "❌ Ваша запись успешно отменена. Администратор уведомлён.", kb_main_menu(user_id))
def handle_admin_list(peer_id: int, user_id: int):
    clean_old_appointments()
    rows = get_all_appointments()
    if not rows:
        send(peer_id, "Активных записей нет.", kb_admin_menu(user_id))
        return
    msg_parts = ["📋 Активные записи:\n"]
    for row in rows:
        date_part, time_part = row["appointment_time"].split()
        d_obj = datetime.strptime(date_part, "%Y-%m-%d").date()
        date_label = format_day_label(d_obj)
        msg_parts.append(
            f"ID: {row['user_id']}\n"
            f"👤 {row['full_name']}\n"
            f"📞 {row['contact']}\n"
            f"💬 {row['topic']}\n"
            f"📅 {date_label} {time_part}\n"
        )
    send(peer_id, "\n".join(msg_parts), kb_admin_menu(user_id))
def handle_admin_delete_start(peer_id: int, user_id: int):
    clean_old_appointments()
    rows = get_all_appointments()
    if not rows:
        send(peer_id, "Активных записей нет.", kb_admin_menu(user_id))
        return
    text = "Введите User ID записи, которую нужно удалить.\n\n"
    text += "Текущие записи:\n"
    for row in rows:
        date_part, time_part = row["appointment_time"].split()
        d_obj = datetime.strptime(date_part, "%Y-%m-%d").date()
        date_label = format_day_label(d_obj)
        text += (
            f"\nID: {row['user_id']}\n"
            f"👤 {row['full_name']}\n"
            f"📞 {row['contact']}\n"
            f"💬 {row['topic']}\n"
            f"📅 {date_label} {time_part}\n"
        )
    set_user_state(user_id, "admin_delete_user_id", {})
    send(peer_id, text, kb_cancel_only())

def handle_admin_delete_user_id(peer_id: int, admin_id: int, text: str):
    if text.lower() == BTN_CANCEL.lower():
        clear_user_state(admin_id)
        send(peer_id, "Удаление отменено.", kb_admin_menu(admin_id))
        return
    try:
        target_user_id = int(text.strip())
    except ValueError:
        send(peer_id, "Введите числовой User ID.", kb_cancel_only())
        return
    rec = get_user_appointment(target_user_id)
    if not rec:
        send(peer_id, "Запись с таким User ID не найдена.", kb_cancel_only())
        return
    full_name, contact, time_str, topic = rec
    data = {
        "target_user_id": target_user_id,
        "full_name": full_name,
        "contact": contact,
        "time_str": time_str,
        "topic": topic,
    }
    set_user_state(admin_id, "admin_delete_reason", data)
    send(peer_id, "Введите причину удаления записи.", kb_cancel_only())
def handle_admin_delete_reason(peer_id: int, admin_id: int, text: str):
    if text.lower() == BTN_CANCEL.lower():
        clear_user_state(admin_id)
        send(peer_id, "Удаление отменено.", kb_admin_menu(admin_id))
        return
    reason = text.strip()
    if len(reason) < 2:
        send(peer_id, "Введите причину удаления.", kb_cancel_only())
        return
    state = get_user_state(admin_id)
    data = state["data"]
    target_user_id = data.get("target_user_id")
    if not target_user_id:
        clear_user_state(admin_id)
        send(peer_id, "Не удалось определить запись для удаления.", kb_admin_menu(admin_id))
        return
    rec = get_user_appointment(target_user_id)
    if not rec:
        clear_user_state(admin_id)
        send(peer_id, "Запись уже отсутствует.", kb_admin_menu(admin_id))
        return
    full_name, contact, time_str, topic = rec
    delete_appointment(target_user_id)
    notify_user_about_admin_cancellation(target_user_id, full_name, time_str, topic, reason)
    notify_admins_about_cancellation(
        target_user_id,
        full_name,
        contact,
        time_str,
        topic,
        reason,
        canceled_by=f"администратором {admin_id}"
    )
    clear_user_state(admin_id)
    send(peer_id, "Запись удалена. Пользователь уведомлён.", kb_admin_menu(admin_id))
def handle_info(peer_id: int, user_id: int, text: str):
    if text == BTN_HELP:
        send(
            peer_id,
            "- Адрес: 40 лет Победы, 11, каб. 1.16\n"
            "- Режим работы: вторник с 14:00 до 18:00, суббота с 9:00 до 13:00\n"
            "- Телефон: 51-55-17, 51-53-00\n"
            "- Email: stud.cons@vgi.volsu.ru\n"
            "- Сайт: https://vgi2.volsu.ru/structure/department/kafedra-yurisprudentsii/uclinic/",
            kb_main_menu(user_id),
        )
    elif text == BTN_DOCS:
        send(peer_id, "- документ, удостоверяющий личность\n- документы по проблеме юридического характера", kb_main_menu(user_id))
    elif text == BTN_COUNS:
        send(peer_id, "Консультации проводят студенты-юристы магистратуры под контролем преподавателей.", kb_main_menu(user_id))
    elif text == BTN_FAQ:
        kb = VkKeyboard(one_time=False)
        kb.add_button(FAQ_1, color=VkKeyboardColor.SECONDARY)
        kb.add_line()
        kb.add_button(FAQ_2, color=VkKeyboardColor.SECONDARY)
        kb.add_line()
        kb.add_button(FAQ_3, color=VkKeyboardColor.SECONDARY)
        kb.add_line()
        kb.add_button(BTN_BACK, color=VkKeyboardColor.SECONDARY)
        send(peer_id, "Выберите интересующий вас вопрос.", kb)
    elif text == FAQ_1:
        send(peer_id, "- устное разъяснение\n- письменный ответ\n- документ правового характера.", kb_main_menu(user_id))
    elif text == FAQ_2:
        send(peer_id, "В зависимости от сложности вопроса — в среднем 7 дней.", kb_main_menu(user_id))
    elif text == FAQ_3:
        send(
            peer_id,
            "ЮК не оказывает услуги по непосредственному представлению интересов граждан в гос. органах, общественных объединениях и иных организациях.",
            kb_main_menu(user_id),
        )
def get_admin_ids():
    try:
        response = vk.groups.getMembers(
            group_id=GROUP_ID,
            filter="managers"
        )
        return [item["id"] for item in response.get("items", [])]
    except Exception:
        return []
def is_admin(user_id: int) -> bool:
    return user_id in set(get_admin_ids())
def notify_admins_about_appointment(user_id: int, full_name: str, contact: str, datetime_str: str, topic: str):
    """Отправляет уведомление администраторам в личные сообщения от имени сообщества."""
    try:
        dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
        formatted_date = f"{dt.day} {RU_MONTHS[dt.month - 1]} {dt.year} г."
        formatted_time = dt.strftime("%H:%M")
        weekday = RU_WEEKDAYS[dt.weekday()].capitalize()
        admin_msg = (
            "📋 Новая запись на консультацию\n\n"
            f"👤 Клиент: {full_name}\n"
            f"📞 Контакт: {contact}\n"
            f"📅 Дата: {formatted_date}\n"
            f"⏰ Время: {formatted_time}\n"
            f"🗓 День недели: {weekday}\n"
            f"💬 Тема: {topic}\n"
            f"🆔 User ID: {user_id}"
        )
        for admin_id in get_admin_ids():
            vk.messages.send(
                user_id=admin_id,
                message=admin_msg,
                random_id=int(time.time() * 1000000) % 2_147_483_647,
                from_group=GROUP_ID
            )
    except Exception as e:
        print(f"Ошибка уведомления админов о новой записи: {e}")
def notify_admins_about_cancellation(user_id: int, full_name: str, contact: str, datetime_str: str, topic: str, reason: str, canceled_by: str):
    """Отправляет уведомление администраторам об отмене записи."""
    try:
        dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
        formatted_date = f"{dt.day} {RU_MONTHS[dt.month - 1]} {dt.year} г."
        formatted_time = dt.strftime("%H:%M")
        weekday = RU_WEEKDAYS[dt.weekday()].capitalize()
        admin_msg = (
            "❌ Отмена записи\n\n"
            f"Кем отменено: {canceled_by}\n"
            f"👤 Клиент: {full_name}\n"
            f"📞 Контакт: {contact}\n"
            f"📅 Дата: {formatted_date}\n"
            f"⏰ Время: {formatted_time}\n"
            f"🗓 День недели: {weekday}\n"
            f"💬 Тема: {topic}\n"
            f"Причина: {reason}\n"
            f"🆔 User ID: {user_id}"
        )
        for admin_id in get_admin_ids():
            vk.messages.send(
                user_id=admin_id,
                message=admin_msg,
                random_id=int(time.time() * 1000000) % 2_147_483_647,
                from_group=GROUP_ID
            )
    except Exception as e:
        print(f"Ошибка уведомления админов об отмене: {e}")
def notify_user_about_admin_cancellation(user_id: int, full_name: str, datetime_str: str, topic: str, reason: str):
    """Уведомляет пользователя об отмене записи администратором."""
    try:
        dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
        formatted_date = f"{dt.day} {RU_MONTHS[dt.month - 1]} {dt.year} г."
        formatted_time = dt.strftime("%H:%M")
        weekday = RU_WEEKDAYS[dt.weekday()].capitalize()
        user_msg = (
            "❌ Ваша запись отменена администратором.\n\n"
            f"👤 ФИО: {full_name}\n"
            f"💬 Тема: {topic}\n"
            f"📅 Дата: {formatted_date}\n"
            f"⏰ Время: {formatted_time}\n"
            f"🗓 День недели: {weekday}\n"
            f"Причина: {reason}\n"
        )
        vk.messages.send(
            user_id=user_id,
            message=user_msg,
            random_id=int(time.time() * 1000000) % 2_147_483_647,
            from_group=GROUP_ID
        )
    except Exception as e:
        print(f"Ошибка уведомления пользователя об отмене: {e}")
def process_event(event):
    if event.type != VkEventType.MESSAGE_NEW:
        return
    if not event.to_me:
        return
    text = (event.text or "").strip()
    user_id = event.user_id
    peer_id = event.user_id
    if text.lower() in {"/start", "start", "старт", "начать"}:
        handle_start(peer_id, user_id)
        return
    step = get_user_state(user_id)["step"]
    if text == BTN_SWITCH_TO_USER and is_admin(user_id):
        set_menu_mode(user_id, "user")
        send(peer_id, "Переключено на меню пользователя.", kb_main_menu(user_id))
        return
    if text == BTN_SWITCH_TO_ADMIN and is_admin(user_id):
        set_menu_mode(user_id, "admin")
        send(peer_id, "Переключено на меню администратора.", kb_admin_menu(user_id))
        return
    if is_admin(user_id):
        if text == BTN_ADMIN_LIST:
            handle_admin_list(peer_id, user_id)
            return
        if text == BTN_ADMIN_DELETE:
            handle_admin_delete_start(peer_id, user_id)
            return
        if step == "admin_delete_user_id":
            handle_admin_delete_user_id(peer_id, user_id, text)
            return
        if step == "admin_delete_reason":
            handle_admin_delete_reason(peer_id, user_id, text)
            return 
    if text == BTN_BACK:
        if is_admin(user_id) and step in {"admin_delete_user_id", "admin_delete_reason"}:
            clear_user_state(user_id)
            if get_menu_mode(user_id) == "admin":
                send(peer_id, "Чем я могу быть вам полезен?", kb_admin_menu(user_id))
            else:
                send(peer_id, "Чем я могу быть вам полезен?", kb_main_menu(user_id))
            return
        if step == "contact":
            clear_user_state(user_id)
            set_user_state(user_id, "name", {})
            send(peer_id, "Введите, пожалуйста, ваше ФИО.", kb_cancel_only())
            return
        if step == "choose_topic":
            handle_choose_topic(peer_id, user_id, BTN_BACK)
            return
        if step == "custom_topic_input":
            state = get_user_state(user_id)
            data = state["data"]
            set_user_state(user_id, "choose_topic", data)
            send(peer_id, "Выберите тему обращения:", kb_topics())
            return
        if step == "choose_day":
            handle_choose_day(peer_id, user_id, BTN_BACK)
            return
        if step == "choose_time":
            handle_choose_time(peer_id, user_id, BTN_BACK)
            return
        if is_admin(user_id) and get_menu_mode(user_id) == "admin":
            send(peer_id, "Чем я могу быть вам полезен?", kb_admin_menu(user_id))
        else:
            send(peer_id, "Чем я могу быть вам полезен?", kb_main_menu(user_id))
        return
    if text == BTN_BOOK:
        handle_book_start(peer_id, user_id)
        return
    if text == BTN_MY:
        handle_my_appointment(peer_id, user_id)
        return
    if text == BTN_CANCEL_BOOK:
        handle_cancel_appointment(peer_id, user_id)
        return
    if text in [BTN_HELP, BTN_DOCS, BTN_COUNS, BTN_FAQ, FAQ_1, FAQ_2, FAQ_3]:
        handle_info(peer_id, user_id, text)
        return 
    if step == "name":
        handle_name(peer_id, user_id, text)
    elif step == "contact":
        handle_contact(peer_id, user_id, text)
    elif step == "choose_topic" or step == "custom_topic_input":
        handle_choose_topic(peer_id, user_id, text)
    elif step == "choose_day":
        handle_choose_day(peer_id, user_id, text)
    elif step == "choose_time":
        handle_choose_time(peer_id, user_id, text)
    else:
        send(peer_id, "Выберите действие в меню ниже.", kb_main_menu(user_id))
def scheduler_loop():
    while True:
        schedule.run_pending()
        time.sleep(60)
schedule.every(14).days.do(clean_old_logs)
schedule.every().hour.do(clean_old_appointments)
schedule.every(30).minutes.do(send_reminders)
def validate_name(name: str) -> bool:
    name = name.strip()
    return 1 <= len(name) <= 64
def validate_contact(contact: str) -> bool:
    c = contact.strip()
    email_re = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    phone_re = re.compile(r'^\+?[\d\s\-\(\)]{7,20}$')
    return bool(email_re.match(c) or phone_re.match(c))
if __name__ == "__main__":
    try:
        init_db()
        threading.Thread(target=scheduler_loop, daemon=True).start()
        print("VK-бот запущен")
        while True:
            try:
                for event in longpoll.listen():
                    try:
                        process_event(event)
                    except Exception as exc:
                        logger.exception("Ошибка обработки события VK")
            except Exception as e:
                logger.exception("Ошибка longpoll соединения")
                time.sleep(5)
    except Exception as e:
        logger.critical("КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ БОТА", exc_info=True)
time.sleep(3)
