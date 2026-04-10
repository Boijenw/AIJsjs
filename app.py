import telebot
from telebot import types
import requests
import json
import time
import os
import sqlite3
import random
import string
import base64
from datetime import datetime, timedelta
from io import BytesIO

# --- НАСТРОЙКИ ---
TOKEN = "8220082028:AAHLdvB5ZKGONVkfSj6uYFdqLiGAIyQS4GE"
OWNER_USERNAME = "@Senko_live"
DEFAULT_TRIAL_DAYS = 7

# API ключ Nano Banana
NANO_API_KEY = "AIzaSyAFpAF3JfC7uNvi_CERMFfAEBnxV6U1tLg"

bot = telebot.TeleBot(TOKEN)

# Бесплатные нейросети
POLLINATIONS_IMAGE_API = "https://image.pollinations.ai/prompt/"
POLLINATIONS_TEXT_API = "https://text.pollinations.ai/"

# --- БАЗА ДАННЫХ (Amvera) ---
DB_PATH = "/data/senko_users.db"
os.makedirs("/data", exist_ok=True)

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
    registered_date TEXT, access_expires TEXT, is_admin INTEGER DEFAULT 0,
    trial_activated INTEGER DEFAULT 0,
    ai_provider TEXT DEFAULT 'pollinations')''')

cursor.execute('''CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY, username TEXT, added_by TEXT)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS promocodes (
    code TEXT PRIMARY KEY, days INTEGER, max_uses INTEGER, used_count INTEGER DEFAULT 0,
    created_by TEXT, created_date TEXT, expires_date TEXT)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS used_promocodes (
    user_id INTEGER, code TEXT, activated_date TEXT, PRIMARY KEY (user_id, code))''')

cursor.execute('''CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY, value TEXT, updated_by TEXT, updated_date TEXT)''')

try:
    cursor.execute("ALTER TABLE users ADD COLUMN ai_provider TEXT DEFAULT 'pollinations'")
except:
    pass

conn.commit()

cursor.execute("INSERT OR IGNORE INTO admins (user_id, username, added_by) VALUES (?, ?, ?)", 
               (0, OWNER_USERNAME, "SYSTEM"))
conn.commit()

print(f"🤖 Бот Senko запущен! База данных: {DB_PATH}")

# --- ФУНКЦИИ ТЕХ. ПЕРЕРЫВА ---
def set_tech_break(status, admin_username):
    cursor.execute('''INSERT OR REPLACE INTO system_settings (key, value, updated_by, updated_date)
    VALUES (?, ?, ?, ?)''', ('tech_break', str(status), admin_username, datetime.now().isoformat()))
    conn.commit()

def is_tech_break():
    cursor.execute("SELECT value FROM system_settings WHERE key = 'tech_break'")
    result = cursor.fetchone()
    if result:
        return result[0] == 'True'
    return False

def get_all_users_for_notify():
    cursor.execute("SELECT user_id FROM users")
    return [row[0] for row in cursor.fetchall()]

def register_user(user_id, username, first_name):
    now = datetime.now()
    cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, first_name, registered_date, trial_activated, ai_provider)
    VALUES (?, ?, ?, ?, ?, ?)''', (user_id, username, first_name, now.isoformat(), 0, 'pollinations'))
    conn.commit()

def activate_trial(user_id):
    now = datetime.now()
    expires = now + timedelta(days=DEFAULT_TRIAL_DAYS)
    cursor.execute('''UPDATE users SET trial_activated = 1, access_expires = ? WHERE user_id = ?''',
                   (expires.isoformat(), user_id))
    conn.commit()
    return expires

def check_access(user_id, username):
    if username == OWNER_USERNAME or f"@{username}" == OWNER_USERNAME:
        return True, "owner"
    
    cursor.execute("SELECT access_expires, trial_activated FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        return False, "not_registered"
    
    expires_str, trial_activated = result
    if trial_activated == 0:
        return False, "trial_not_activated"
    
    if expires_str:
        expires = datetime.fromisoformat(expires_str)
        if datetime.now() > expires:
            return False, "expired"
    
    return True, "active"

def is_admin(user_id, username):
    if username == OWNER_USERNAME or f"@{username}" == OWNER_USERNAME:
        return True
    cursor.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None

def generate_promo_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def get_user_ai_provider(user_id):
    cursor.execute("SELECT ai_provider FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 'pollinations'

def set_user_ai_provider(user_id, provider):
    cursor.execute("UPDATE users SET ai_provider = ? WHERE user_id = ?", (provider, user_id))
    conn.commit()

# --- ГЕНЕРАЦИЯ КАРТИНОК (ИСПРАВЛЕНО) ---
def generate_image_nano(prompt):
    if not NANO_API_KEY:
        return None, "Ключ API не настроен"
    
    # Исправленная модель для картинок
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp-image-generation:generateContent?key={NANO_API_KEY}"
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"]
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=60)
        if response.status_code == 200:
            data = response.json()
            for part in data['candidates'][0]['content']['parts']:
                if 'inlineData' in part:
                    return base64.b64decode(part['inlineData']['data']), None
            return None, "Изображение не найдено в ответе"
        else:
            error_msg = f"Ошибка API: {response.status_code}"
            try:
                error_data = response.json()
                if 'error' in error_data:
                    error_msg = error_data['error'].get('message', error_msg)
            except:
                pass
            return None, error_msg
    except Exception as e:
        return None, str(e)

def generate_image_pollinations(prompt):
    try:
        safe_prompt = requests.utils.quote(prompt)
        image_url = f"{POLLINATIONS_IMAGE_API}{safe_prompt}?width=1024&height=1024&nologo=true&seed={random.randint(1, 999999)}"
        response = requests.get(image_url, timeout=60)
        if response.status_code == 200:
            return response.content, None
        return None, f"Ошибка Pollinations: {response.status_code}"
    except Exception as e:
        return None, str(e)

# --- ГЕНЕРАЦИЯ ТЕКСТА (ИСПРАВЛЕНО) ---
def generate_text_nano(prompt, system_prompt=""):
    if not NANO_API_KEY:
        return None, "Ключ API не настроен"
    
    # Исправленная модель для текста
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={NANO_API_KEY}"
    
    full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
    
    payload = {
        "contents": [{
            "parts": [{"text": full_prompt}]
        }]
    }
    
    try:
        response = requests.post(url, json=payload, timeout=45)
        if response.status_code == 200:
            data = response.json()
            return data['candidates'][0]['content']['parts'][0]['text'], None
        else:
            error_msg = f"Ошибка API: {response.status_code}"
            try:
                error_data = response.json()
                if 'error' in error_data:
                    error_msg = error_data['error'].get('message', error_msg)
            except:
                pass
            return None, error_msg
    except Exception as e:
        return None, str(e)

def generate_text_pollinations(prompt, system_prompt=""):
    try:
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "model": "openai",
            "seed": random.randint(1, 999999)
        }
        response = requests.post(POLLINATIONS_TEXT_API, json=payload, timeout=45)
        if response.status_code == 200:
            return response.text, None
        return None, f"Ошибка Pollinations: {response.status_code}"
    except Exception as e:
        return None, str(e)

# --- КЛАВИАТУРЫ ---
def trial_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🎁 Активировать 7 дней бесплатно")
    markup.add("🎫 Активировать промокод")
    markup.add("🛠 Поддержка")
    return markup

def main_menu(user_id=None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📝 Задать вопрос", "💻 Написать код")
    markup.add("🎨 Нарисовать картинку", "ℹ️ Помощь")
    markup.add("🛠 Поддержка", "🎫 Активировать промокод")
    
    # Кнопка переключения нейросети
    if user_id:
        provider = get_user_ai_provider(user_id)
        if provider == 'nano':
            markup.add("🔄 Переключить на Pollinations (бесплатно)")
        else:
            markup.add("🔄 Переключить на Nano Banana")
    
    return markup

def back_button():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 Главное меню")
    return markup

def admin_panel():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🤖 Нейросеть", "👥 Пользователи")
    markup.add("➕ Продлить доступ", "🎁 Создать промокод")
    markup.add("📋 Список промокодов", "👑 Добавить админа")
    markup.add("❌ Удалить админа", "📊 Статистика")
    markup.add("📨 Рассылка")
    if is_tech_break():
        markup.add("🟢 Включить бота")
    else:
        markup.add("🔴 Технический перерыв")
    markup.add("🔙 Главное меню")
    return markup

# --- /start ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    first_name = message.from_user.first_name or "Пользователь"
    
    register_user(user_id, username, first_name)
    
    if is_tech_break() and username != OWNER_USERNAME and f"@{username}" != OWNER_USERNAME:
        bot.send_message(
            message.chat.id,
            "🔧 *Бот находится на техническом обслуживании*\n\n"
            "⏳ Пожалуйста, подождите немного.\n"
            "Мы скоро вернемся и вы получите уведомление!",
            parse_mode='Markdown'
        )
        return
    
    has_access, status = check_access(user_id, username)
    
    if not has_access:
        if status == "trial_not_activated":
            bot.send_message(
                message.chat.id,
                f"👋 Привет, {first_name}!\n\n"
                f"🎁 *7 дней бесплатного доступа* ко всем функциям!\n\n"
                f"Нажми кнопку ниже для активации.",
                parse_mode='Markdown',
                reply_markup=trial_keyboard()
            )
        elif status == "expired":
            bot.send_message(
                message.chat.id,
                f"❌ *Доступ закончился!*\n\n"
                f"Активируйте промокод или напишите {OWNER_USERNAME}",
                parse_mode='Markdown',
                reply_markup=trial_keyboard()
            )
        return
    
    welcome_text = f"👋 С возвращением, {first_name}!\n\n"
    
    if status == "owner" or is_admin(user_id, username):
        welcome_text += "👑 *Админ-панель*\n\n"
        welcome_text += "Нажми *🤖 Нейросеть*, чтобы задавать вопросы и генерировать картинки!"
        bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=admin_panel())
    else:
        cursor.execute("SELECT access_expires FROM users WHERE user_id = ?", (user_id,))
        expires = datetime.fromisoformat(cursor.fetchone()[0])
        days_left = (expires - datetime.now()).days
        provider = get_user_ai_provider(user_id)
        provider_name = "Nano Banana" if provider == 'nano' else "Pollinations (бесплатно)"
        welcome_text += f"⏳ Доступ: *{days_left}* дней\n"
        welcome_text += f"🤖 Нейросеть: *{provider_name}*"
        bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown', reply_markup=main_menu(user_id))

# --- ОБРАБОТКА КНОПОК ---
@bot.message_handler(func=lambda message: True)
def handle_buttons(message):
    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    text = message.text
    
    if is_tech_break() and username != OWNER_USERNAME and f"@{username}" != OWNER_USERNAME:
        if text not in ["🛠 Поддержка"]:
            bot.reply_to(message, "🔧 *Технический перерыв*\n\nБот временно недоступен.", parse_mode='Markdown')
            return
    
    # 🎁 АКТИВАЦИЯ ТРИАЛА
    if text == "🎁 Активировать 7 дней бесплатно":
        cursor.execute("SELECT trial_activated FROM users WHERE user_id = ?", (user_id,))
        if cursor.fetchone()[0] == 1:
            bot.reply_to(message, "❌ Вы уже активировали пробный период!")
            return
        expires = activate_trial(user_id)
        bot.send_message(message.chat.id,
            f"✅ *Пробный период активирован!*\n\n🎉 7 дней бесплатного доступа!\n📅 До: {expires.strftime('%d.%m.%Y')}",
            parse_mode='Markdown', reply_markup=main_menu(user_id))
        return
    
    # 🎫 АКТИВАЦИЯ ПРОМОКОДА
    elif text == "🎫 Активировать промокод":
        msg = bot.reply_to(message, "🔑 Введите промокод:", reply_markup=back_button())
        bot.register_next_step_handler(msg, process_promocode_activation)
        return
    
    # 🔄 ПЕРЕКЛЮЧЕНИЕ НЕЙРОСЕТИ
    elif text == "🔄 Переключить на Nano Banana":
        set_user_ai_provider(user_id, 'nano')
        bot.reply_to(message, "✅ Нейросеть переключена на *Nano Banana*!", parse_mode='Markdown', reply_markup=main_menu(user_id))
        return
    
    elif text == "🔄 Переключить на Pollinations (бесплатно)":
        set_user_ai_provider(user_id, 'pollinations')
        bot.reply_to(message, "✅ Нейросеть переключена на *Pollinations (бесплатно)*!", parse_mode='Markdown', reply_markup=main_menu(user_id))
        return
    
    has_access, status = check_access(user_id, username)
    
    if not has_access and text not in ["🛠 Поддержка", "🔙 Главное меню", "🎁 Активировать 7 дней бесплатно", "🎫 Активировать промокод"]:
        bot.reply_to(message, "❌ *Доступ закончился!*", parse_mode='Markdown')
        return
    
    # 🔙 ГЛАВНОЕ МЕНЮ
    if text == "🔙 Главное меню":
        if is_admin(user_id, username):
            bot.send_message(message.chat.id, "🏠 Админ-панель:", reply_markup=admin_panel())
        else:
            bot.send_message(message.chat.id, "🏠 Главное меню:", reply_markup=main_menu(user_id))
    
    # 🤖 НЕЙРОСЕТЬ (для админов)
    elif text == "🤖 Нейросеть":
        if is_admin(user_id, username):
            bot.send_message(message.chat.id, "🤖 *Режим нейросети активирован!*", parse_mode='Markdown', reply_markup=main_menu(user_id))
    
    # 📝 ЗАДАТЬ ВОПРОС
    elif text == "📝 Задать вопрос":
        msg = bot.reply_to(message, "✏️ Напиши свой вопрос:", reply_markup=back_button())
        bot.register_next_step_handler(msg, process_question)
    
    # 💻 НАПИСАТЬ КОД
    elif text == "💻 Написать код":
        msg = bot.reply_to(message, "💻 Опиши, какой код нужен:", reply_markup=back_button())
        bot.register_next_step_handler(msg, process_code)
    
    # 🎨 НАРИСОВАТЬ КАРТИНКУ
    elif text == "🎨 Нарисовать картинку":
        msg = bot.reply_to(message, "🎨 Опиши, что нарисовать:", reply_markup=back_button())
        bot.register_next_step_handler(msg, process_image)
    
    # ℹ️ ПОМОЩЬ
    elif text == "ℹ️ Помощь":
        help_text = (
            "📚 *Помощь по боту Senko*\n\n"
            "• 📝 Задать вопрос — ответ на любой вопрос\n"
            "• 💻 Написать код — генерация кода\n"
            "• 🎨 Нарисовать картинку — создание изображений\n"
            "• 🔄 Переключить нейросеть — выбор между Nano Banana и Pollinations\n"
            f"📞 *Поддержка:* {OWNER_USERNAME}"
        )
        bot.send_message(message.chat.id, help_text, parse_mode='Markdown')
    
    # 🛠 ПОДДЕРЖКА
    elif text == "🛠 Поддержка":
        support_text = f"🛠 *Техническая поддержка Senko*\n\n👨‍💻 *Разработчик:* {OWNER_USERNAME}\n\n📋 *По вопросам:*\n• Продление доступа\n• Получение промокода\n• Ошибки и предложения\n\n⏰ Ответ в течение 24 часов"
        bot.send_message(message.chat.id, support_text, parse_mode='Markdown')
    
    # 👑 АДМИН-ПАНЕЛЬ
    elif is_admin(user_id, username):
        if text == "🔴 Технический перерыв":
            set_tech_break(True, username)
            users = get_all_users_for_notify()
            notify_count = 0
            for uid in users:
                if uid != user_id:
                    try:
                        bot.send_message(uid, "🔧 *Уведомление*\n\nБот Senko уходит на техническое обслуживание.\n⏳ Мы скоро вернемся!", parse_mode='Markdown')
                        notify_count += 1
                    except: pass
            bot.send_message(message.chat.id, f"🔴 *Технический перерыв активирован!*\n\n✅ Уведомления отправлены {notify_count} пользователям.", parse_mode='Markdown', reply_markup=admin_panel())
        
        elif text == "🟢 Включить бота":
            set_tech_break(False, username)
            users = get_all_users_for_notify()
            notify_count = 0
            for uid in users:
                if uid != user_id:
                    try:
                        bot.send_message(uid, "🟢 *Бот Senko снова в строю!*\n\n✨ Техническое обслуживание завершено.\n🎉 Можете продолжать пользоваться!", parse_mode='Markdown')
                        notify_count += 1
                    except: pass
            bot.send_message(message.chat.id, f"🟢 *Бот включен!*\n\n✅ Уведомления отправлены {notify_count} пользователям.", parse_mode='Markdown', reply_markup=admin_panel())
        
        elif text == "👥 Пользователи":
            cursor.execute("SELECT user_id, username, first_name, access_expires, trial_activated, ai_provider FROM users LIMIT 15")
            users = cursor.fetchall()
            if not users:
                bot.reply_to(message, "📭 Нет пользователей")
                return
            response = "👥 *Пользователи:*\n\n"
            for uid, uname, fname, exp, trial, provider in users:
                emoji = "✅" if trial else "⏳"
                if exp:
                    exp_date = datetime.fromisoformat(exp)
                    days_left = (exp_date - datetime.now()).days
                    emoji = "❌" if days_left < 0 else emoji
                    days_str = f"{days_left} дн."
                else:
                    days_str = "не акт."
                prov = "Nano" if provider == 'nano' else "Polli"
                response += f"{emoji} @{uname} — {days_str} [{prov}]\n"
            bot.send_message(message.chat.id, response, parse_mode='Markdown')
        
        elif text == "➕ Продлить доступ":
            msg = bot.reply_to(message, "Введите @username и дни (например: @user 30):", reply_markup=back_button())
            bot.register_next_step_handler(msg, process_extend_access)
        
        elif text == "🎁 Создать промокод":
            msg = bot.reply_to(message, "Формат: `дни макс_исп срок_дней`\nПример: `30 100 90`", parse_mode='Markdown', reply_markup=back_button())
            bot.register_next_step_handler(msg, process_create_promocode)
        
        elif text == "📋 Список промокодов":
            cursor.execute("SELECT code, days, max_uses, used_count FROM promocodes LIMIT 10")
            promos = cursor.fetchall()
            if not promos:
                bot.reply_to(message, "📭 Нет промокодов")
                return
            response = "🎁 *Промокоды:*\n\n"
            for code, days, max_uses, used in promos:
                status = "✅" if used < max_uses else "❌"
                response += f"{status} *{code}* — {days} дн. ({used}/{max_uses})\n"
            bot.send_message(message.chat.id, response, parse_mode='Markdown')
        
        elif text == "👑 Добавить админа":
            msg = bot.reply_to(message, "Введите @username:", reply_markup=back_button())
            bot.register_next_step_handler(msg, process_add_admin)
        
        elif text == "❌ Удалить админа":
            cursor.execute("SELECT user_id, username FROM admins WHERE username != ?", (OWNER_USERNAME,))
            admins = cursor.fetchall()
            if not admins:
                bot.reply_to(message, "Нет админов")
                return
            response = "Выберите номер:\n\n"
            for i, (uid, uname) in enumerate(admins, 1):
                response += f"{i}. @{uname}\n"
            msg = bot.reply_to(message, response, reply_markup=back_button())
            bot.register_next_step_handler(msg, process_remove_admin, admins)
        
        elif text == "📊 Статистика":
            cursor.execute("SELECT COUNT(*) FROM users")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE trial_activated = 1")
            active = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE ai_provider = 'nano'")
            nano_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE ai_provider = 'pollinations'")
            polli_users = cursor.fetchone()[0]
            stats = f"📊 *Статистика*\n\n👥 Всего: {total}\n✅ Активных: {active}\n🤖 Nano: {nano_users}\n🆓 Pollinations: {polli_users}\n🔧 Тех. перерыв: {'🔴 Да' if is_tech_break() else '🟢 Нет'}"
            bot.send_message(message.chat.id, stats, parse_mode='Markdown')
        
        elif text == "📨 Рассылка":
            msg = bot.reply_to(message, "📝 Введите сообщение для рассылки:", reply_markup=back_button())
            bot.register_next_step_handler(msg, process_broadcast)

# --- ФУНКЦИИ ОБРАБОТКИ ---
def process_question(message):
    if message.text == "🔙 Главное меню":
        handle_buttons(message)
        return
    
    user_id = message.from_user.id
    provider = get_user_ai_provider(user_id)
    
    bot.send_chat_action(message.chat.id, 'typing')
    
    if provider == 'nano':
        answer, error = generate_text_nano(message.text, "Ты Senko, полезный ассистент. Отвечай на русском.")
    else:
        answer, error = generate_text_pollinations(message.text, "Ты Senko, полезный ассистент. Отвечай на русском.")
    
    if error:
        # Если ошибка, пробуем Pollinations как запасной вариант
        if provider == 'nano':
            bot.reply_to(message, f"⚠️ Nano Banana недоступен: {error}\n\n🔄 Переключаю на Pollinations...")
            set_user_ai_provider(user_id, 'pollinations')
            answer, error = generate_text_pollinations(message.text, "Ты Senko, полезный ассистент. Отвечай на русском.")
            if error:
                bot.reply_to(message, f"❌ Ошибка: {error}")
                return
        else:
            bot.reply_to(message, f"❌ Ошибка: {error}")
            return
    
    if len(answer) > 4000:
        for x in range(0, len(answer), 4000):
            bot.reply_to(message, answer[x:x+4000])
    else:
        bot.reply_to(message, answer, parse_mode='Markdown')

def process_code(message):
    if message.text == "🔙 Главное меню":
        handle_buttons(message)
        return
    
    user_id = message.from_user.id
    provider = get_user_ai_provider(user_id)
    
    bot.send_chat_action(message.chat.id, 'typing')
    
    system_prompt = "Ты программист. Отвечай ТОЛЬКО кодом с краткими комментариями. Не добавляй лишнего текста."
    
    if provider == 'nano':
        answer, error = generate_text_nano(message.text, system_prompt)
    else:
        answer, error = generate_text_pollinations(message.text, system_prompt)
    
    if error:
        if provider == 'nano':
            bot.reply_to(message, f"⚠️ Nano Banana недоступен: {error}\n\n🔄 Переключаю на Pollinations...")
            set_user_ai_provider(user_id, 'pollinations')
            answer, error = generate_text_pollinations(message.text, system_prompt)
            if error:
                bot.reply_to(message, f"❌ Ошибка: {error}")
                return
        else:
            bot.reply_to(message, f"❌ Ошибка: {error}")
            return
    
    if "```" not in answer:
        answer = f"```\n{answer}\n```"
    bot.reply_to(message, answer, parse_mode='Markdown')

def process_image(message):
    if message.text == "🔙 Главное меню":
        handle_buttons(message)
        return
    
    user_id = message.from_user.id
    provider = get_user_ai_provider(user_id)
    
    bot.send_chat_action(message.chat.id, 'upload_photo')
    status_msg = bot.reply_to(message, f"🎨 Рисую через {provider.upper()}...", parse_mode='Markdown')
    
    image_data = None
    error_msg = None
    
    if provider == 'nano':
        image_data, error_msg = generate_image_nano(message.text)
        if error_msg:
            bot.edit_message_text(f"⚠️ Nano Banana: {error_msg}\n\n🔄 Переключаю на Pollinations...", message.chat.id, status_msg.message_id)
            set_user_ai_provider(user_id, 'pollinations')
            image_data, error_msg = generate_image_pollinations(message.text)
    else:
        image_data, error_msg = generate_image_pollinations(message.text)
    
    if image_data:
        bot.send_photo(message.chat.id, image_data, caption=f"🖼 *{message.text}*", parse_mode='Markdown', reply_to_message_id=message.message_id)
        bot.delete_message(message.chat.id, status_msg.message_id)
    else:
        bot.edit_message_text(f"❌ Не удалось сгенерировать: {error_msg}", message.chat.id, status_msg.message_id)

def process_promocode_activation(message):
    if message.text == "🔙 Главное меню":
        handle_buttons(message)
        return
    
    code = message.text.upper().strip()
    cursor.execute('SELECT code, days, max_uses, used_count, expires_date FROM promocodes WHERE code = ?', (code,))
    promo = cursor.fetchone()
    
    if not promo:
        bot.reply_to(message, "❌ Промокод не найден", reply_markup=main_menu(message.from_user.id))
        return
    
    promo_code, days, max_uses, used_count, expires_date = promo
    
    if expires_date and datetime.now() > datetime.fromisoformat(expires_date):
        bot.reply_to(message, "❌ Срок действия промокода истек", reply_markup=main_menu(message.from_user.id))
        return
    
    if used_count >= max_uses:
        bot.reply_to(message, "❌ Промокод исчерпан", reply_markup=main_menu(message.from_user.id))
        return
    
    cursor.execute('SELECT * FROM used_promocodes WHERE user_id = ? AND code = ?', (message.from_user.id, code))
    if cursor.fetchone():
        bot.reply_to(message, "❌ Вы уже использовали этот промокод", reply_markup=main_menu(message.from_user.id))
        return
    
    cursor.execute("SELECT access_expires FROM users WHERE user_id = ?", (message.from_user.id,))
    result = cursor.fetchone()
    
    if result and result[0]:
        current = datetime.fromisoformat(result[0])
        new_expires = (current if current > datetime.now() else datetime.now()) + timedelta(days=days)
    else:
        new_expires = datetime.now() + timedelta(days=days)
    
    cursor.execute("UPDATE users SET access_expires = ?, trial_activated = 1 WHERE user_id = ?", (new_expires.isoformat(), message.from_user.id))
    cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code,))
    cursor.execute("INSERT INTO used_promocodes (user_id, code, activated_date) VALUES (?, ?, ?)", (message.from_user.id, code, datetime.now().isoformat()))
    conn.commit()
    
    bot.send_message(message.chat.id, f"✅ *Промокод активирован!*\n\n🎉 Доступ продлен на {days} дней!\n📅 До: {new_expires.strftime('%d.%m.%Y')}", parse_mode='Markdown', reply_markup=main_menu(message.from_user.id))

def process_extend_access(message):
    if message.text == "🔙 Главное меню":
        handle_buttons(message)
        return
    try:
        parts = message.text.split()
        username = parts[0].replace("@", "")
        days = int(parts[1])
        cursor.execute("SELECT user_id FROM users WHERE username = ?", (username,))
        result = cursor.fetchone()
        if not result:
            bot.reply_to(message, "❌ Пользователь не найден", reply_markup=admin_panel())
            return
        user_id = result[0]
        cursor.execute("SELECT access_expires FROM users WHERE user_id = ?", (user_id,))
        current = cursor.fetchone()
        if current and current[0]:
            current_date = datetime.fromisoformat(current[0])
            new_expires = (current_date if current_date > datetime.now() else datetime.now()) + timedelta(days=days)
        else:
            new_expires = datetime.now() + timedelta(days=days)
        cursor.execute("UPDATE users SET access_expires = ?, trial_activated = 1 WHERE user_id = ?", (new_expires.isoformat(), user_id))
        conn.commit()
        bot.send_message(message.chat.id, f"✅ Доступ для @{username} продлен на {days} дней\n📅 До: {new_expires.strftime('%d.%m.%Y')}", reply_markup=admin_panel())
        try:
            bot.send_message(user_id, f"🎉 *Ваш доступ продлен!*\n\n📅 Доступ активен до: {new_expires.strftime('%d.%m.%Y')}\nСпасибо, что вы с нами! ❤️", parse_mode='Markdown')
        except:
            pass
    except:
        bot.reply_to(message, "❌ Неверный формат. Пример: @user 30", reply_markup=admin_panel())

def process_create_promocode(message):
    if message.text == "🔙 Главное меню":
        handle_buttons(message)
        return
    try:
        parts = message.text.split()
        days = int(parts[0])
        max_uses = int(parts[1])
        expires_days = int(parts[2]) if len(parts) > 2 else None
        code = generate_promo_code()
        now = datetime.now()
        expires_date = now + timedelta(days=expires_days) if expires_days else None
        cursor.execute('INSERT INTO promocodes (code, days, max_uses, created_by, created_date, expires_date) VALUES (?, ?, ?, ?, ?, ?)',
                       (code, days, max_uses, message.from_user.username or "admin", now.isoformat(), expires_date.isoformat() if expires_date else None))
        conn.commit()
        bot.send_message(message.chat.id, f"✅ *Промокод создан!*\n\n🎫 Код: `{code}`\n📅 Дней: {days}\n👥 Использований: {max_uses}\n⏳ Истекает: {expires_date.strftime('%d.%m.%Y') if expires_date else 'Никогда'}", parse_mode='Markdown', reply_markup=admin_panel())
    except:
        bot.reply_to(message, "❌ Неверный формат. Пример: 30 100 90", reply_markup=admin_panel())

def process_add_admin(message):
    if message.text == "🔙 Главное меню":
        handle_buttons(message)
        return
    username = message.text.replace("@", "")
    cursor.execute("SELECT user_id FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    if not result:
        bot.reply_to(message, "❌ Пользователь не найден в базе", reply_markup=admin_panel())
        return
    user_id = result[0]
    cursor.execute("INSERT OR IGNORE INTO admins (user_id, username, added_by) VALUES (?, ?, ?)", (user_id, username, message.from_user.username or "admin"))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ @{username} добавлен в администраторы!", reply_markup=admin_panel())

def process_remove_admin(message, admins):
    if message.text == "🔙 Главное меню":
        handle_buttons(message)
        return
    try:
        index = int(message.text) - 1
        if 0 <= index < len(admins):
            user_id, username = admins[index]
            cursor.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
            conn.commit()
            bot.send_message(message.chat.id, f"✅ @{username} удален из администраторов", reply_markup=admin_panel())
        else:
            bot.reply_to(message, "❌ Неверный номер", reply_markup=admin_panel())
    except:
        bot.reply_to(message, "❌ Введите номер", reply_markup=admin_panel())

def process_broadcast(message):
    if message.text == "🔙 Главное меню":
        handle_buttons(message)
        return
    
    broadcast_text = message.text
    users = get_all_users_for_notify()
    success_count = 0
    fail_count = 0
    
    status_msg = bot.reply_to(message, f"📨 Начинаю рассылку на {len(users)} пользователей...")
    
    for uid in users:
        try:
            bot.send_message(uid, f"📢 *Сообщение от разработчика:*\n\n{broadcast_text}", parse_mode='Markdown')
            success_count += 1
            time.sleep(0.05)
        except:
            fail_count += 1
    
    bot.edit_message_text(f"✅ *Рассылка завершена!*\n\n📨 Отправлено: {success_count}\n❌ Ошибок: {fail_count}", message.chat.id, status_msg.message_id, parse_mode='Markdown')
    bot.send_message(message.chat.id, "🏠 Админ-панель:", reply_markup=admin_panel())

# --- ЗАПУСК ---
if __name__ == "__main__":
    print("🚀 Бот Senko запускается на Amvera...")
    bot.polling(none_stop=False, interval=0, timeout=20)