import sqlite3
import logging
from datetime import datetime, date, timedelta
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import asyncio
from typing import Optional
import re
import random
import string

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("vosemyata.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Токен бота
BOT_TOKEN = "8035757633:AAG0_AQQJxkdRQzLcWSDJw2h82sA1Mg31sg"
ADMINS = [5171361978, 8268613975, 2143824530]

# Инициализация
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)
router = Router()

# Подключение к базе данных
conn = sqlite3.connect("vosemyata.db", check_same_thread=False)
cursor = conn.cursor()

# === КОНСТАНТЫ ===
BACK_BUTTON = "⬅️ Назад"
MSG_ONLY_IN_GROUP = "❌ Эта команда доступна только в группе."
MSG_ONLY_IN_PRIVATE = "❌ Команда доступна только в личных сообщениях."
MSG_ACCESS_DENIED = "❌ Доступ запрещён."
MSG_ONLY_IN_PRIVATE_ALERT = "❌ Команда доступна только в личных сообщениях."
MSG_ACCESS_DENIED_ALERT = "❌ Доступ запрещён."

# === ФУНКЦИЯ ОБНОВЛЕНИЯ СХЕМЫ БД ===
def ensure_schema():
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            first_name TEXT,
            last_name TEXT,
            join_date TEXT DEFAULT CURRENT_TIMESTAMP,
            total_requests INTEGER DEFAULT 0,
            approved_requests INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            weekly_claimed_date TEXT DEFAULT NULL,
            bank_balance INTEGER DEFAULT 0,
            profile_description TEXT DEFAULT NULL,
            profile_skin TEXT DEFAULT NULL,
            last_daily_bonus TEXT DEFAULT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            reason TEXT,
            media_id TEXT DEFAULT NULL,
            media_type TEXT DEFAULT NULL,
            status TEXT DEFAULT 'pending',
            admin_id INTEGER DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shop (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price INTEGER,
            description TEXT DEFAULT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            amount INTEGER,
            date TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT DEFAULT CURRENT_TIMESTAMP,
            total_requests INTEGER DEFAULT 0,
            approved_requests INTEGER DEFAULT 0,
            total_transfers INTEGER DEFAULT 0,
            total_amount_transferred INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            amount INTEGER,
            message TEXT DEFAULT NULL,
            date TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            game_type TEXT,
            bet INTEGER,
            result INTEGER,
            date TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            message TEXT,
            date TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS promocodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            reward INTEGER,
            uses_limit INTEGER,
            uses_count INTEGER DEFAULT 0,
            creator_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT DEFAULT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS promocode_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            promocode_id INTEGER,
            user_id INTEGER,
            used_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Проверяем, существуют ли столбцы
    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'level' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1")
        cursor.execute("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE users ADD COLUMN weekly_claimed_date TEXT DEFAULT NULL")
        cursor.execute("ALTER TABLE users ADD COLUMN bank_balance INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE users ADD COLUMN profile_description TEXT DEFAULT NULL")
        cursor.execute("ALTER TABLE users ADD COLUMN profile_skin TEXT DEFAULT NULL")
        cursor.execute("ALTER TABLE users ADD COLUMN last_daily_bonus TEXT DEFAULT NULL")
        print("✅ Новые столбцы добавлены в таблицу users")

    conn.commit()

ensure_schema()

def get_user_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def get_user_bank_balance(user_id):
    cursor.execute("SELECT bank_balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def update_balance(user_id, amount, username="unknown", first_name=None, last_name=None):
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        new_balance = result[0] + amount
        cursor.execute(
            "UPDATE users SET balance = ?, username = ?, first_name = ?, last_name = ? WHERE user_id = ?",
            (new_balance, username, first_name, last_name, user_id)
        )
    else:
        cursor.execute(
            "INSERT INTO users (user_id, username, balance, first_name, last_name) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, amount, first_name, last_name)
        )
    conn.commit()
    logging.info(f"ADJUST | User: {user_id} (@{username}) | Amount: {amount} | New: {get_user_balance(user_id)}")

def add_xp(user_id, xp_amount):
    cursor.execute("SELECT xp, level FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        current_xp, current_level = result
        new_xp = current_xp + xp_amount
        new_level = current_level
        # Уровень повышается каждые 100 XP
        while new_xp >= 100:
            new_xp -= 100
            new_level += 1
        cursor.execute("UPDATE users SET xp = ?, level = ? WHERE user_id = ?", (new_xp, new_level, user_id))
        conn.commit()
        return new_level
    return 1

def get_user_level(user_id):
    cursor.execute("SELECT level, xp FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result if result else (1, 0)

def add_request(user_id, username, first_name, reason, media_id=None, media_type=None):
    cursor.execute(
        "INSERT INTO requests (user_id, username, first_name, reason, media_id, media_type) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username, first_name, reason, media_id, media_type)
    )
    cursor.execute("UPDATE users SET total_requests = total_requests + 1 WHERE user_id = ?", (user_id,))
    conn.commit()

def get_pending_requests():
    cursor.execute("SELECT id, user_id, username, first_name, reason, media_id, media_type FROM requests WHERE status = 'pending'")
    return cursor.fetchall()

def get_request_history(limit=20):
    cursor.execute("SELECT id, user_id, username, reason, status, admin_id FROM requests ORDER BY id DESC LIMIT ?", (limit,))
    return cursor.fetchall()

def update_request_status(req_id, status, admin_id):
    cursor.execute("UPDATE requests SET status = ?, admin_id = ? WHERE id = ?", (status, admin_id, req_id))
    if status == 'approved':
        cursor.execute("SELECT user_id FROM requests WHERE id = ?", (req_id,))
        user_id = cursor.fetchone()[0]
        update_balance(user_id, 8)
        add_xp(user_id, 10)
        cursor.execute("UPDATE users SET approved_requests = approved_requests + 1 WHERE user_id = ?", (user_id,))
        logging.info(f"APPROVE | Request #{req_id} | User: {user_id} | Admin: {admin_id}")
    elif status == 'declined':
        cursor.execute("SELECT user_id FROM requests WHERE id = ?", (req_id,))
        user_id = cursor.fetchone()[0]
        logging.info(f"DECLINE | Request #{req_id} | User: {user_id} | Admin: {admin_id}")
    conn.commit()

def get_shop_items():
    cursor.execute("SELECT id, name, price, description FROM shop")
    return cursor.fetchall()

def add_item_to_shop(name, price, description=None):
    cursor.execute("INSERT INTO shop (name, price, description) VALUES (?, ?, ?)", (name, price, description))
    conn.commit()

def get_top_users(limit=10):
    cursor.execute("SELECT user_id, username, first_name, balance, level FROM users ORDER BY balance DESC LIMIT ?", (limit,))
    return cursor.fetchall()

def buy_item_by_id(user_id, item_id):
    items = get_shop_items()
    item = next((i for i in items if i[0] == item_id), None)
    if not item:
        return False, "Товар не найден"
    price = item[2]
    balance = get_user_balance(user_id)
    if balance < price:
        return False, "Недостаточно восьмерят"
    update_balance(user_id, -price)
    return True, f"Вы купили {item[1]}!"

def get_user_stats(user_id):
    cursor.execute("SELECT total_requests, approved_requests FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result if result else (0, 0)

def get_daily_stats():
    today = date.today().isoformat()
    cursor.execute("SELECT * FROM daily_stats WHERE date = ?", (today,))
    result = cursor.fetchone()
    if not result:
        cursor.execute(
            "INSERT INTO daily_stats (date, total_requests, approved_requests, total_transfers, total_amount_transferred) VALUES (?, 0, 0, 0, 0)",
            (today,)
        )
        conn.commit()
        return (today, 0, 0, 0, 0)
    return result

def update_daily_stats(requests=0, approved=0, transfers=0, amount=0):
    today = date.today().isoformat()
    cursor.execute(
        "UPDATE daily_stats SET total_requests = total_requests + ?, approved_requests = approved_requests + ?, total_transfers = total_transfers + ?, total_amount_transferred = total_amount_transferred + ? WHERE date = ?",
        (requests, approved, transfers, amount, today)
    )
    conn.commit()

def add_feedback(user_id, feedback_type, message):
    cursor.execute("INSERT INTO feedback (user_id, type, message) VALUES (?, ?, ?)", (user_id, feedback_type, message))
    conn.commit()

def get_pending_feedback():
    cursor.execute("SELECT id, user_id, type, message FROM feedback WHERE status = 'pending'")
    return cursor.fetchall()

# === ФУНКЦИИ ДЛЯ ПРОМОКОДОВ ===
def generate_promocode(length=8):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def create_promocode(reward, uses_limit, expires_at=None):
    code = generate_promocode()
    cursor.execute(
        "INSERT INTO promocodes (code, reward, uses_limit, creator_id) VALUES (?, ?, ?, ?)",
        (code, reward, uses_limit, 0)  # creator_id временно 0, будет обновлён в вызывающем коде
    )
    conn.commit()
    return code

def get_promocode_by_code(code):
    cursor.execute("SELECT * FROM promocodes WHERE code = ?", (code,))
    return cursor.fetchone()

def use_promocode(code, user_id):
    promocode = get_promocode_by_code(code)
    if not promocode:
        return False, "Промокод не найден"
    
    promocode_id, code, reward, uses_limit, uses_count, creator_id, created_at, expires_at = promocode
    
    if expires_at and datetime.now() > datetime.fromisoformat(expires_at):
        return False, "Срок действия промокода истёк"
    
    if uses_count >= uses_limit:
        return False, "Лимит использований промокода исчерпан"
    
    # Проверяем, использовал ли пользователь этот промокод
    cursor.execute("SELECT * FROM promocode_uses WHERE promocode_id = ? AND user_id = ?", (promocode_id, user_id))
    if cursor.fetchone():
        return False, "Вы уже использовали этот промокод"
    
    # Начисляем награду
    update_balance(user_id, reward, "", "", "")
    
    # Обновляем счётчик использований
    cursor.execute("UPDATE promocodes SET uses_count = uses_count + 1 WHERE id = ?", (promocode_id,))
    
    # Сохраняем использование
    cursor.execute("INSERT INTO promocode_uses (promocode_id, user_id) VALUES (?, ?)", (promocode_id, user_id))
    
    conn.commit()
    return True, f"✅ Вы получили {reward} восьмерят по промокоду!"

def delete_promocode(code):
    cursor.execute("DELETE FROM promocodes WHERE code = ?", (code,))
    conn.commit()

def get_all_promocodes():
    cursor.execute("SELECT * FROM promocodes ORDER BY created_at DESC")
    return cursor.fetchall()

# === ПРОВЕРКИ ===
def is_private_chat(message: Message) -> bool:
    return message.chat.type == "private"

def is_group_chat(message: Message) -> bool:
    return message.chat.type in ["group", "supergroup"]

def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

# === НОВАЯ ФУНКЦИЯ: проверка лимита переводов в день ===
def get_transfer_count_today(sender_id, receiver_id):
    today = date.today().isoformat()
    cursor.execute(
        "SELECT COUNT(*) FROM transfers WHERE sender_id = ? AND receiver_id = ? AND date = ?",
        (sender_id, receiver_id, today)
    )
    return cursor.fetchone()[0]

def add_transfer(sender_id, receiver_id, amount):
    today = date.today().isoformat()
    cursor.execute(
        "INSERT INTO transfers (sender_id, receiver_id, amount, date) VALUES (?, ?, ?, ?)",
        (sender_id, receiver_id, amount, today)
    )
    update_daily_stats(transfers=1, amount=amount)
    conn.commit()

# === КНОПКИ ===
def back_to_main():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text=BACK_BUTTON, callback_data="back_to_main")
    return builder.as_markup()

# === ОБЩИЕ КОМАНДЫ (работают только в группе) ===
@router.message(Command("start"))
async def cmd_start(message: Message):
    if is_group_chat(message):
        await message.answer("Привет! Это бот восьмерята. Используй /balance, /apply_vosemyata, /shop.")
    else:
        await message.answer("Привет! Это бот восьмерята.\n\n"
                             "Доступные команды:\n"
                             "/balance - проверить баланс\n"
                             "/apply_vosemyata - подать заявку\n"
                             "/shop - магазин\n"
                             "/top - топ пользователей\n"
                             "/transfer - перевести восьмеряти\n"
                             "/stats - статистика\n"
                             "/weekly - получить еженедельную награду\n"
                             "/bank - банк\n"
                             "/profile - профиль\n"
                             "/gift - подарить восьмеряти\n"
                             "/dice - игра в кости\n"
                             "/rank - уровень\n"
                             "/feedback - отправить отзыв\n"
                             "/bug_report - сообщить об ошибке\n"
                             "/suggest - предложить улучшение\n"
                             "/use_promocode - использовать промокод\n"
                             "/create_promocode - создать промокод (только для админов)")

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    balance = get_user_balance(message.from_user.id)
    total_req, approved_req = get_user_stats(message.from_user.id)
    level, xp = get_user_level(message.from_user.id)
    await message.answer(f"Ваш баланс: {balance} восьмерят.\n"
                         f"Уровень: {level} (XP: {xp}/100)\n"
                         f"Заявок подано: {total_req}\n"
                         f"Одобрено: {approved_req}")

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    total_req, approved_req = get_user_stats(message.from_user.id)
    success_rate = (approved_req / total_req * 100) if total_req > 0 else 0
    level, xp = get_user_level(message.from_user.id)
    await message.answer(f"📊 Ваша статистика:\n"
                         f"Уровень: {level} (XP: {xp}/100)\n"
                         f"Заявок подано: {total_req}\n"
                         f"Одобрено: {approved_req}\n"
                         f"Успешность: {success_rate:.1f}%")

@router.message(Command("rank"))
async def cmd_rank(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    level, xp = get_user_level(message.from_user.id)
    await message.answer(f"🏆 Ваш уровень: {level}\n"
                         f"Опыт: {xp}/100\n"
                         f"До следующего уровня: {100 - xp} XP")

@router.message(Command("weekly"))
async def cmd_weekly(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    
    cursor.execute("SELECT weekly_claimed_date FROM users WHERE user_id = ?", (message.from_user.id,))
    result = cursor.fetchone()
    last_claimed = result[0] if result else None
    
    if last_claimed:
        try:
            last_date = datetime.fromisoformat(last_claimed)
            if datetime.now() - last_date < timedelta(days=7):
                days_left = 7 - (datetime.now() - last_date).days
                await message.answer(f"❌ Вы уже получили еженедельную награду. Приходите через {days_left} дней.")
                return
        except ValueError:
            pass
    
    reward = 50  # базовая награда
    level, _ = get_user_level(message.from_user.id)
    bonus = level * 5  # бонус за уровень
    total_reward = reward + bonus
    
    update_balance(message.from_user.id, total_reward, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    cursor.execute("UPDATE users SET weekly_claimed_date = ? WHERE user_id = ?", (datetime.now().isoformat(), message.from_user.id))
    conn.commit()
    
    await message.answer(f"🎉 Вы получили еженедельную награду: {total_reward} восьмерят! (База: {reward}, Бонус: {bonus})")

@router.message(Command("bank"))
async def cmd_bank(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    
    balance = get_user_balance(message.from_user.id)
    bank_balance = get_user_bank_balance(message.from_user.id)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Положить", callback_data="bank_deposit")
    builder.button(text="💸 Снять", callback_data="bank_withdraw")
    builder.button(text="📊 Инфо", callback_data="bank_info")
    
    await message.answer(f"🏦 Банк восьмерят:\n"
                         f"Ваш баланс: {balance} восьмерят\n"
                         f"В банке: {bank_balance} восьмерят", 
                         reply_markup=builder.as_markup())

@router.message(Command("profile"))
async def cmd_profile(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    
    cursor.execute("SELECT username, first_name, last_name, profile_description, profile_skin FROM users WHERE user_id = ?", (message.from_user.id,))
    result = cursor.fetchone()
    if not result:
        await message.answer("❌ Вы ещё не зарегистрированы. Сделайте что-нибудь в боте.")
        return
    
    username, first_name, last_name, description, skin = result
    full_name = f"{first_name or ''} {last_name or ''}".strip() or username
    level, xp = get_user_level(message.from_user.id)
    balance = get_user_balance(message.from_user.id)
    
    skin_text = f" | Скин: {skin}" if skin else ""
    
    profile_text = f"👤 Профиль {full_name} (@{username}){skin_text}\n"
    profile_text += f"💰 Баланс: {balance} восьмерят\n"
    profile_text += f"🏆 Уровень: {level} (XP: {xp}/100)\n"
    
    if description:
        profile_text += f"📝 Описание: {description}\n"
    
    profile_text += f"\n/setskin - сменить скин\n/setdesc - сменить описание"
    
    await message.answer(profile_text)

@router.message(Command("setskin"))
async def cmd_set_skin(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Используйте: /setskin названиеСкина")
        return
    
    skin = args[1]
    cursor.execute("UPDATE users SET profile_skin = ? WHERE user_id = ?", (skin, message.from_user.id))
    conn.commit()
    await message.answer(f"✅ Скин изменён на: {skin}")

@router.message(Command("setdesc"))
async def cmd_set_desc(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Используйте: /setdesc вашеОписание")
        return
    
    desc = args[1]
    cursor.execute("UPDATE users SET profile_description = ? WHERE user_id = ?", (desc, message.from_user.id))
    conn.commit()
    await message.answer(f"✅ Описание изменено на: {desc}")

@router.message(Command("gift"))
async def cmd_gift(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Используйте: /gift @username количество сообщение")
        return
    
    target_username = args[1]
    try:
        amount = int(args[2])
    except ValueError:
        await message.answer("Количество должно быть числом.")
        return
    
    gift_message = args[3] if len(args) > 3 else "Без сообщения"
    
    if amount <= 0:
        await message.answer("Количество должно быть положительным.")
        return
    
    sender_balance = get_user_balance(message.from_user.id)
    if sender_balance < amount:
        await message.answer("❌ Недостаточно восьмерят для подарка.")
        return
    
    cursor.execute("SELECT user_id FROM users WHERE username = ?", (target_username[1:],))
    receiver = cursor.fetchone()
    
    if not receiver:
        await message.answer(f"❌ Пользователь {target_username} не найден.")
        return
    
    receiver_id, = receiver
    if receiver_id == message.from_user.id:
        await message.answer("❌ Нельзя подарить самому себе.")
        return
    
    update_balance(message.from_user.id, -amount, message.from_user.username)
    update_balance(receiver_id, amount, target_username[1:])
    
    cursor.execute("INSERT INTO gifts (sender_id, receiver_id, amount, message) VALUES (?, ?, ?, ?)",
                   (message.from_user.id, receiver_id, amount, gift_message))
    conn.commit()
    
    try:
        await bot.send_message(receiver_id, f"🎁 Вам подарили {amount} восьмерят от @{message.from_user.username}!\nСообщение: {gift_message}")
    except Exception:
        pass
    
    await message.answer(f"🎁 Вы подарили {amount} восьмерят пользователю {target_username} с сообщением: {gift_message}")

@router.message(Command("dice"))
async def cmd_dice(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Используйте: /dice ставка")
        return
    
    try:
        bet = int(args[1])
    except ValueError:
        await message.answer("Ставка должна быть числом.")
        return
    
    if bet <= 0:
        await message.answer("Ставка должна быть положительной.")
        return
    
    balance = get_user_balance(message.from_user.id)
    if balance < bet:
        await message.answer("❌ Недостаточно восьмерят для ставки.")
        return
    
    bot_roll = random.randint(1, 6)
    user_roll = random.randint(1, 6)
    
    if user_roll > bot_roll:
        win_amount = bet * 2
        update_balance(message.from_user.id, win_amount, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
        result_text = f"🎲 Вы бросили {user_roll}, бот бросил {bot_roll}. Вы выиграли {win_amount} восьмерят!"
    elif user_roll < bot_roll:
        update_balance(message.from_user.id, -bet, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
        result_text = f"🎲 Вы бросили {user_roll}, бот бросил {bot_roll}. Вы проиграли {bet} восьмерят."
    else:
        result_text = f"🎲 Вы бросили {user_roll}, бот бросил {bot_roll}. Ничья! Ставка возвращена."
    
    cursor.execute("INSERT INTO games (user_id, game_type, bet, result) VALUES (?, ?, ?, ?)",
                   (message.from_user.id, "dice", bet, 1 if user_roll > bot_roll else (-1 if user_roll < bot_roll else 0)))
    conn.commit()
    
    await message.answer(result_text)

# === СИСТЕМА ОБРАТНОЙ СВЯЗИ ===
@router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext):
    if not is_private_chat(message):
        await message.answer(MSG_ONLY_IN_PRIVATE)
        return
    
    await message.answer("Введите ваш отзыв:")
    await state.set_state(FeedbackStates.feedback_message)

@router.message(Command("bug_report"))
async def cmd_bug_report(message: Message, state: FSMContext):
    if not is_private_chat(message):
        await message.answer(MSG_ONLY_IN_PRIVATE)
        return
    
    await message.answer("Опишите ошибку, которую вы нашли:")
    await state.set_state(FeedbackStates.bug_message)

@router.message(Command("suggest"))
async def cmd_suggest(message: Message, state: FSMContext):
    if not is_private_chat(message):
        await message.answer(MSG_ONLY_IN_PRIVATE)
        return
    
    await message.answer("Предложите улучшение для бота:")
    await state.set_state(FeedbackStates.suggestion_message)

class FeedbackStates(StatesGroup):
    feedback_message = State()
    bug_message = State()
    suggestion_message = State()

@router.message(FeedbackStates.feedback_message)
async def process_feedback(message: Message, state: FSMContext):
    add_feedback(message.from_user.id, "feedback", message.text)
    await message.answer("✅ Спасибо за ваш отзыв! Мы рассмотрим его в ближайшее время.")
    await state.clear()

@router.message(FeedbackStates.bug_message)
async def process_bug_report(message: Message, state: FSMContext):
    add_feedback(message.from_user.id, "bug", message.text)
    await message.answer("✅ Спасибо за сообщение об ошибке! Мы постараемся исправить её как можно скорее.")
    await state.clear()

@router.message(FeedbackStates.suggestion_message)
async def process_suggestion(message: Message, state: FSMContext):
    add_feedback(message.from_user.id, "suggestion", message.text)
    await message.answer("✅ Спасибо за ваше предложение! Мы рассмотрим его.")
    await state.clear()

# === СИСТЕМА ПРОМОКОДОВ ===
@router.message(Command("use_promocode"))
async def cmd_use_promocode(message: Message, state: FSMContext):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    
    await message.answer("Введите промокод:")
    await state.set_state(PromocodeStates.code)

class PromocodeStates(StatesGroup):
    code = State()

@router.message(PromocodeStates.code)
async def process_promocode(message: Message, state: FSMContext):
    code = message.text.strip()
    success, result = use_promocode(code, message.from_user.id)
    
    if success:
        await message.answer(result)
    else:
        await message.answer(result)
    
    await state.clear()

# === КОМАНДА ДЛЯ СОЗДАНИЯ ПРОМОКОДОВ (только для админов) ===
@router.message(Command(["create_promocode", "cp"]))
async def cmd_create_promocode(message: Message, state: FSMContext):
    if not is_private_chat(message):
        await message.answer(MSG_ONLY_IN_PRIVATE)
        return
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ACCESS_DENIED)
        return
    
    await message.answer("Введите награду за промокод (в восьмерятах):")
    await state.set_state(AdminPromocodeStates.create_reward)

@router.message(Command("apply_vosemyata"))
async def cmd_apply(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Используйте: /apply_vosemyata Причина получения")
        return
    reason = args[1]

    # Проверяем, есть ли медиа
    media_id = None
    media_type = None

    if message.photo:
        media_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        media_id = message.video.file_id
        media_type = "video"
    elif message.document:
        media_id = message.document.file_id
        media_type = "document"
    elif message.voice:
        media_id = message.voice.file_id
        media_type = "voice"
    elif message.audio:
        media_id = message.audio.file_id
        media_type = "audio"
    elif message.video_note:
        media_id = message.video_note.file_id
        media_type = "video_note"

    update_balance(
        message.from_user.id,
        0,
        message.from_user.username or "unknown",
        message.from_user.first_name,
        message.from_user.last_name
    )
    add_request(
        message.from_user.id,
        message.from_user.username or "unknown",
        message.from_user.first_name,
        reason,
        media_id,
        media_type
    )
    update_daily_stats(requests=1)
    await message.answer("Ваша заявка отправлена на проверку администратору.")

@router.message(lambda m: m.photo or m.video or m.document or m.voice or m.audio or m.video_note)
async def handle_media_with_caption(message: Message):
    if not is_group_chat(message):
        return

    # Проверяем, есть ли описание (caption)
    if not message.caption:
        await message.answer("❌ Отправьте фото/видео с описанием, содержащим команду: /apply_vosemyata Причина получения")
        return

    # Проверяем, начинается ли описание с команды
    if not message.caption.startswith("/apply_vosemyata"):
        await message.answer("❌ Чтобы отправить заявку, начните описание с команды: /apply_vosemyata Причина получения")
        return

    # Извлекаем причину из описания
    args = message.caption.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Используйте: /apply_vosemyata Причина получения")
        return
    reason = args[1]

    # Получаем тип и ID медиа
    media_id = None
    media_type = None

    if message.photo:
        media_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        media_id = message.video.file_id
        media_type = "video"
    elif message.document:
        media_id = message.document.file_id
        media_type = "document"
    elif message.voice:
        media_id = message.voice.file_id
        media_type = "voice"
    elif message.audio:
        media_id = message.audio.file_id
        media_type = "audio"
    elif message.video_note:
        media_id = message.video_note.file_id
        media_type = "video_note"

    update_balance(
        message.from_user.id,
        0,
        message.from_user.username or "unknown",
        message.from_user.first_name,
        message.from_user.last_name
    )
    add_request(
        message.from_user.id,
        message.from_user.username or "unknown",
        message.from_user.first_name,
        reason,
        media_id,
        media_type
    )
    update_daily_stats(requests=1)
    await message.answer("Ваша заявка отправлена на проверку администратору.")

@router.message(Command("shop"))
async def cmd_shop(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    items = get_shop_items()
    if not items:
        await message.answer("Магазин пуст.")
        return
    text = "🛍 Магазин восьмерят:\n\n"
    for item in items:
        text += f"{item[0]}. {item[1]} — {item[2]} восьмерят\n"
        if item[3]:  # description
            text += f"   {item[3]}\n"
        text += "\n"
    text += "Чтобы купить, введите номер товара."
    await message.answer(text)

@router.message(lambda m: m.text and m.text.isdigit())
async def handle_number_input(message: Message):
    if not is_group_chat(message):
        return
    try:
        item_id = int(message.text)
        success, msg = buy_item_by_id(message.from_user.id, item_id)
        await message.answer(msg)
    except Exception:
        await message.answer("Неверный формат. Введите номер товара из /shop.")

@router.message(Command("top"))
async def cmd_top(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    top_users = get_top_users()
    if not top_users:
        await message.answer("Нет данных для топа.")
        return
    text = "🏆 Топ-10 по восьмерятам:\n\n"
    for i, user in enumerate(top_users, start=1):
        text += f"{i}. {user[2] or user[1] or 'unknown'} — {user[3]} восьмерят (Ур. {user[4]})\n"
    await message.answer(text)

@router.message(Command("transfer"))
async def cmd_transfer(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return

    args = message.text.split()
    if len(args) != 3:
        await message.answer("Используйте: /transfer @username количество")
        return

    target_username = args[1]
    try:
        amount = int(args[2])
    except ValueError:
        await message.answer("Количество должно быть числом.")
        return

    if amount <= 0:
        await message.answer("Переводить можно только положительное количество.")
        return

    sender_id = message.from_user.id
    sender_balance = get_user_balance(sender_id)

    if sender_balance < amount:
        await message.answer("❌ Недостаточно восьмерят для перевода.")
        return

    # === ПРОВЕРКА ЛИМИТА: 3 перевода в день ===
    cursor.execute("SELECT user_id FROM users WHERE username = ?", (target_username[1:],))
    receiver = cursor.fetchone()

    if not receiver:
        await message.answer(f"❌ Пользователь {target_username} не найден. Убедитесь, что он уже писал боту.")
        return

    receiver_id, = receiver

    if receiver_id == sender_id:
        await message.answer("❌ Нельзя перевести самому себе.")
        return

    # Проверяем лимит
    count_today = get_transfer_count_today(sender_id, receiver_id)
    if count_today >= 3:
        await message.answer("❌ Вы уже перевели 3 раза этому пользователю сегодня.")
        return

    # Выполняем перевод
    update_balance(sender_id, -amount, message.from_user.username)
    update_balance(receiver_id, amount, target_username[1:])

    # === СОХРАНЯЕМ ПЕРЕВОД В ИСТОРИЮ ===
    add_transfer(sender_id, receiver_id, amount)

    # Уведомляем обоих
    try:
        await bot.send_message(sender_id, f"✅ Вы перевели {amount} восьмерят пользователю {target_username}.")
    except Exception:
        pass

    try:
        await bot.send_message(receiver_id, f"💰 Вам перевели {amount} восьмерят от @{message.from_user.username}!")
    except Exception:
        pass

    await message.answer(f"✅ Перевод выполнен: @{message.from_user.username} → {target_username}: {amount} восьмерят.")

# === КОЛБЭКИ БАНКА ===
@router.callback_query(lambda c: c.data == "bank_deposit")
async def bank_deposit_prompt(call: CallbackQuery, state: FSMContext):
    if not is_group_chat(call.message):
        await call.answer("❌ Эта функция доступна только в группе.", show_alert=True)
        return
    await call.message.answer("Введите сумму для внесения в банк:")
    await state.set_state(BankStates.deposit_amount)

@router.callback_query(lambda c: c.data == "bank_withdraw")
async def bank_withdraw_prompt(call: CallbackQuery, state: FSMContext):
    if not is_group_chat(call.message):
        await call.answer("❌ Эта функция доступна только в группе.", show_alert=True)
        return
    await call.message.answer("Введите сумму для снятия из банка:")
    await state.set_state(BankStates.withdraw_amount)

@router.callback_query(lambda c: c.data == "bank_info")
async def bank_info(call: CallbackQuery):
    balance = get_user_balance(call.from_user.id)
    bank_balance = get_user_bank_balance(call.from_user.id)
    await call.message.answer(f"🏦 Информация о банке:\n"
                              f"Ваш баланс: {balance} восьмерят\n"
                              f"В банке: {bank_balance} восьмерят\n"
                              f"Проценты: 1% в день от суммы в банке")

class BankStates(StatesGroup):
    deposit_amount = State()
    withdraw_amount = State()

@router.message(BankStates.deposit_amount)
async def process_deposit(message: Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("Сумма должна быть положительной.")
            return
        
        user_balance = get_user_balance(message.from_user.id)
        if user_balance < amount:
            await message.answer("❌ Недостаточно восьмерят для внесения.")
            return
        
        update_balance(message.from_user.id, -amount, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
        cursor.execute("UPDATE users SET bank_balance = bank_balance + ? WHERE user_id = ?", (amount, message.from_user.id))
        conn.commit()
        
        await message.answer(f"✅ Внесено {amount} восьмерят в банк.")
    except ValueError:
        await message.answer("Введите корректное число.")
    finally:
        await state.clear()

@router.message(BankStates.withdraw_amount)
async def process_withdraw(message: Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("Сумма должна быть положительной.")
            return
        
        bank_balance = get_user_bank_balance(message.from_user.id)
        if bank_balance < amount:
            await message.answer("❌ Недостаточно восьмерят в банке.")
            return
        
        update_balance(message.from_user.id, amount, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
        cursor.execute("UPDATE users SET bank_balance = bank_balance - ? WHERE user_id = ?", (amount, message.from_user.id))
        conn.commit()
        
        await message.answer(f"✅ Снято {amount} восьмерят из банка.")
    except ValueError:
        await message.answer("Введите корректное число.")
    finally:
        await state.clear()

# === АДМИН-КОМАНДЫ (работают только в ЛС) ===
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_private_chat(message):
        await message.answer(MSG_ONLY_IN_PRIVATE)
        return
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ACCESS_DENIED)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Заявки", callback_data="admin_requests")
    builder.button(text="💬 Обратная связь", callback_data="admin_feedback")
    builder.button(text="🏷️ Промокоды", callback_data="admin_promocodes")
    builder.button(text="🛒 Магазин", callback_data="admin_shop")
    builder.button(text="👥 Топ", callback_data="admin_top")
    builder.button(text="📜 История", callback_data="admin_history")
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="💰 Выдать/списать", callback_data="admin_adjust_menu")
    await message.answer("Админ-панель восьмерят:", reply_markup=builder.as_markup())

@router.message(Command("adjust"))
async def cmd_adjust(message: Message):
    if not is_private_chat(message):
        await message.answer(MSG_ONLY_IN_PRIVATE)
        return
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ACCESS_DENIED)
        return
    try:
        parts = message.text.split()
        if len(parts) != 3:
            raise ValueError()
        user_id = int(parts[1])
        amount = int(parts[2])

        # Проверяем, существует ли пользователь
        cursor.execute("SELECT username, first_name FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            await message.answer(f"❌ Пользователь с ID {user_id} не найден. Убедитесь, что он хотя бы раз написал боту.")
            return

        username = user[0]
        first_name = user[1]
        update_balance(user_id, amount, username, first_name)
        action = "начислено" if amount > 0 else "снято"
        await message.answer(f"✅ {abs(amount)} восьмерят {action} пользователю {first_name or username} (ID: {user_id}).")
        try:
            await bot.send_message(user_id, f"🔔 Админ {action} {abs(amount)} восьмерят. Новое значение: {get_user_balance(user_id)}")
        except Exception:
            pass
    except ValueError:
        await message.answer("Используйте: /adjust USER_ID КОЛИЧЕСТВО\n(например: /adjust 123456789 8)")
    except Exception as e:
        logging.error(f"Ошибка в /adjust: {e}")
        await message.answer("❌ Произошла ошибка. Проверьте логи.")

@router.message(Command("profile"))
async def cmd_profile_admin(message: Message):
    if not is_private_chat(message):
        await message.answer(MSG_ONLY_IN_PRIVATE)
        return
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ACCESS_DENIED)
        return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Используйте: /profile USER_ID")
        return
    try:
        user_id = int(args[1])
        balance = get_user_balance(user_id)
        cursor.execute("SELECT username, first_name, last_name FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            await message.answer("Пользователь не найден.")
            return
        username, first_name, last_name = user
        full_name = f"{first_name or ''} {last_name or ''}".strip() or username

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        builder.button(text="💰 Перевести", callback_data=f"transfer_to_{user_id}")
        builder.button(text="📊 Статистика", callback_data=f"stats_user_{user_id}")
        builder.button(text=BACK_BUTTON, callback_data="back_to_main")
        
        cursor.execute("SELECT COUNT(*) FROM requests WHERE user_id = ?", (user_id,))
        total_requests = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM requests WHERE user_id = ? AND status = 'approved'", (user_id,))
        approved = cursor.fetchone()[0]
        await message.answer(
            f"👤 Профиль {full_name} (ID: {user_id})\n"
            f"💰 Баланс: {balance} восьмерят\n"
            f"📊 Заявок всего: {total_requests}\n"
            f"✅ Одобрено: {approved}",
            reply_markup=builder.as_markup()
        )
    except ValueError:
        await message.answer("Неверный ID.")

# === КНОПКА "ПЕРЕВЕСТИ" В ПРОФИЛЕ ===
@router.callback_query(lambda c: c.data.startswith("transfer_to_"))
async def transfer_to_user(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return

    target_user_id = int(call.data.split("_")[2])
    await call.message.edit_text(f"Введите сумму для перевода пользователю с ID {target_user_id}:\n\nПример: /adjust {target_user_id} 8")
    await call.answer()

# === АДМИН-ПАНЕЛЬ ПРОМОКОДОВ ===
@router.callback_query(lambda c: c.data == "admin_promocodes")
async def admin_promocodes(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    
    promocodes = get_all_promocodes()
    if not promocodes:
        text = "🏷️ Нет созданных промокодов."
    else:
        text = "🏷️ Все промокоды:\n\n"
        for p in promocodes:
            _, code, reward, uses_limit, uses_count, creator_id, created_at, expires_at = p
            status = f" ({uses_count}/{uses_limit})" if uses_limit != 0 else ""
            expires = f" (до {expires_at})" if expires_at else ""
            text += f"• `{code}`: {reward} восьмерят{status}{expires}\n"
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать", callback_data="create_promocode")
    builder.button(text="🗑️ Удалить", callback_data="delete_promocode")
    builder.button(text=BACK_BUTTON, callback_data="back_to_main")
    
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()

@router.callback_query(lambda c: c.data == "create_promocode")
async def create_promocode_prompt(call: CallbackQuery, state: FSMContext):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    
    await call.message.answer("Введите награду за промокод (в восьмерятах):")
    await state.set_state(AdminPromocodeStates.create_reward)

@router.callback_query(lambda c: c.data == "delete_promocode")
async def delete_promocode_prompt(call: CallbackQuery, state: FSMContext):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    
    await call.message.answer("Введите промокод для удаления:")
    await state.set_state(AdminPromocodeStates.delete_code)

class AdminPromocodeStates(StatesGroup):
    create_reward = State()
    create_uses = State()
    create_expires = State()
    delete_code = State()

@router.message(AdminPromocodeStates.create_reward)
async def create_promocode_reward(message: Message, state: FSMContext):
    try:
        reward = int(message.text)
        if reward <= 0:
            await message.answer("Награда должна быть положительной.")
            return
        await state.update_data(reward=reward)
        await message.answer("Введите лимит использований (0 для бесконечного):")
        await state.set_state(AdminPromocodeStates.create_uses)
    except ValueError:
        await message.answer("Введите корректное число.")

@router.message(AdminPromocodeStates.create_uses)
async def create_promocode_uses(message: Message, state: FSMContext):
    try:
        uses = int(message.text)
        if uses < 0:
            await message.answer("Лимит должен быть неотрицательным.")
            return
        await state.update_data(uses=uses)
        await message.answer("Введите срок действия в днях (0 для бессрочного, макс. 365):")
        await state.set_state(AdminPromocodeStates.create_expires)
    except ValueError:
        await message.answer("Введите корректное число.")

@router.message(AdminPromocodeStates.create_expires)
async def create_promocode_expires(message: Message, state: FSMContext):
    try:
        days = int(message.text)
        if days < 0 or days > 365:
            await message.answer("Введите число от 0 до 365.")
            return
        
        data = await state.get_data()
        reward = data['reward']
        uses = data['uses']
        
        expires_at = None
        if days > 0:
            expires_at = (datetime.now() + timedelta(days=days)).isoformat()
        
        code = create_promocode(reward, uses if uses > 0 else 999999, expires_at)
        cursor.execute("UPDATE promocodes SET creator_id = ? WHERE code = ?", (message.from_user.id, code))
        conn.commit()
        
        await message.answer(f"✅ Промокод создан:\n\n`{code}`\nНаграда: {reward} восьмерят\nЛимит: {uses if uses > 0 else 'бесконечный'}\nСрок: {'бессрочный' if days == 0 else f'{days} дней'}")
    except ValueError:
        await message.answer("Введите корректное число.")
    finally:
        await state.clear()

@router.message(AdminPromocodeStates.delete_code)
async def delete_promocode_process(message: Message, state: FSMContext):
    code = message.text.strip()
    promocode = get_promocode_by_code(code)
    
    if not promocode:
        await message.answer("❌ Промокод не найден.")
    else:
        delete_promocode(code)
        await message.answer(f"✅ Промокод `{code}` удалён.")
    
    await state.clear()

# === ОСТАЛЬНЫЕ КОЛБЭКИ ===
@router.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_menu(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Заявки", callback_data="admin_requests")
    builder.button(text="💬 Обратная связь", callback_data="admin_feedback")
    builder.button(text="🏷️ Промокоды", callback_data="admin_promocodes")
    builder.button(text="🛒 Магазин", callback_data="admin_shop")
    builder.button(text="👥 Топ", callback_data="admin_top")
    builder.button(text="📜 История", callback_data="admin_history")
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="💰 Выдать/списать", callback_data="admin_adjust_menu")
    
    await call.message.edit_text("Админ-панель восьмерят:", reply_markup=builder.as_markup())
    await call.answer()

@router.callback_query(lambda c: c.data == "admin_requests")
async def admin_requests(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    requests = get_pending_requests()
    if not requests:
        await call.message.edit_text("Нет новых заявок.", reply_markup=back_to_main())
        await call.answer()
        return

    text = "📋 Новые заявки:\n\n"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for r in requests:
        text += f"ID {r[0]} от {r[3] or r[2]}: {r[4]}\n"
        builder.button(text=f"✅ Одобрить #{r[0]}", callback_data=f"approve_{r[0]}")
        builder.button(text=f"❌ Отклонить #{r[0]}", callback_data=f"decline_{r[0]}")
    builder.button(text=BACK_BUTTON, callback_data="back_to_main")
    
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()

@router.callback_query(lambda c: c.data == "admin_feedback")
async def admin_feedback(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    
    feedbacks = get_pending_feedback()
    if not feedbacks:
        await call.message.edit_text("Нет новых сообщений обратной связи.", reply_markup=back_to_main())
        await call.answer()
        return

    text = "💬 Новые сообщения обратной связи:\n\n"
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for f in feedbacks:
        text += f"ID {f[0]} от {f[1]} ({f[2]}): {f[3]}\n\n"
        builder.button(text=f"✅ Отметить #{f[0]}", callback_data=f"feedback_done_{f[0]}")
    builder.button(text=BACK_BUTTON, callback_data="back_to_main")
    
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()

@router.callback_query(lambda c: c.data.startswith("feedback_done_"))
async def feedback_done(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    
    feedback_id = int(call.data.split("_")[2])
    cursor.execute("UPDATE feedback SET status = 'done' WHERE id = ?", (feedback_id,))
    conn.commit()
    
    await call.answer("✅ Сообщение отмечено как обработанное.")
    await admin_feedback(call)

# === Отправка медиа админу при одобрении/отклонении ===
async def send_media_to_admin(req_id, user_id, reason, media_id, media_type, admin_id, action):
    try:
        # Получаем юзернейм
        user = await bot.get_chat(user_id)
        username = user.username or "unknown"
        first_name = user.first_name or "unknown"

        caption = f"Заявка #{req_id} от {first_name} (@{username})\nПричина: {reason}\nДействие: {action}"

        if media_id and media_type:
            if media_type == "photo":
                await bot.send_photo(chat_id=admin_id, photo=media_id, caption=caption)
            elif media_type == "video":
                await bot.send_video(chat_id=admin_id, video=media_id, caption=caption)
            elif media_type == "document":
                await bot.send_document(chat_id=admin_id, document=media_id, caption=caption)
            elif media_type == "voice":
                await bot.send_voice(chat_id=admin_id, voice=media_id, caption=caption)
            elif media_type == "audio":
                await bot.send_audio(chat_id=admin_id, audio=media_id, caption=caption)
            elif media_type == "video_note":
                await bot.send_video_note(chat_id=admin_id, video_note=media_id)
        else:
            await bot.send_message(chat_id=admin_id, text=f"Заявка #{req_id} от {first_name} (@{username})\nПричина: {reason}\nДействие: {action}")
    except Exception as e:
        logging.error(f"Ошибка при отправке медиа админу {admin_id}: {e}")

@router.callback_query(lambda c: c.data.startswith("approve_"))
async def approve_request(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    req_id = int(call.data.split("_")[1])
    cursor.execute("SELECT user_id, reason, media_id, media_type FROM requests WHERE id = ?", (req_id,))
    row = cursor.fetchone()
    if not row:
        await call.answer("Заявка не найдена.", show_alert=True)
        return
    user_id, reason, media_id, media_type = row

    update_request_status(req_id, 'approved', call.from_user.id)
    update_daily_stats(approved=1)

    try:
        await bot.send_message(user_id, f"✅ Ваша заявка #{req_id} одобрена! 8 восьмерят зачислено.")
    except Exception:
        pass

    await send_media_to_admin(req_id, user_id, reason, media_id, media_type, call.from_user.id, "✅ Одобрено")
    await admin_requests(call)

@router.callback_query(lambda c: c.data.startswith("decline_"))
async def decline_request(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    req_id = int(call.data.split("_")[1])
    cursor.execute("SELECT user_id, reason, media_id, media_type FROM requests WHERE id = ?", (req_id,))
    row = cursor.fetchone()
    if not row:
        await call.answer("Заявка не найдена.", show_alert=True)
        return
    user_id, reason, media_id, media_type = row

    update_request_status(req_id, 'declined', call.from_user.id)

    try:
        await bot.send_message(user_id, f"❌ Ваша заявка #{req_id} отклонена администратором.")
    except Exception:
        pass

    await send_media_to_admin(req_id, user_id, reason, media_id, media_type, call.from_user.id, "❌ Отклонено")
    await admin_requests(call)

@router.callback_query(lambda c: c.data == "admin_shop")
async def admin_shop(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    items = get_shop_items()
    text = "🛒 Товары в магазине:\n\n"
    for item in items:
        text += f"{item[0]}. {item[1]} — {item[2]} восьмерят\n"
        if item[3]:  # description
            text += f"   {item[3]}\n"
        text += "\n"
    text += "Чтобы добавить товар, нажмите кнопку ниже."
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить товар", callback_data="admin_add_item_prompt")
    builder.button(text=BACK_BUTTON, callback_data="back_to_main")
    
    await call.message.edit_text(text, reply_markup=builder.as_markup())
    await call.answer()

@router.callback_query(lambda c: c.data == "admin_add_item_prompt")
async def admin_add_item_prompt(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    await call.message.edit_text("Введите название, цену и описание товара в формате:\n\nНазвание Цена Описание")
    await call.answer()

@router.message(lambda m: m.text and re.match(r"^[^0-9].+ \d+ .+$", m.text))
async def handle_add_item(message: Message):
    if not is_private_chat(message):
        return
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ACCESS_DENIED)
        return
    try:
        parts = message.text.rsplit(" ", 2)
        name = parts[0].strip()
        price = int(parts[1])
        description = parts[2]
        add_item_to_shop(name, price, description)
        await message.answer(f"Товар '{name}' добавлен в магазин за {price} восьмерят.\nОписание: {description}")
    except ValueError:
        await message.answer("Неверный формат. Введите: Название Цена Описание")
    except Exception:
        await message.answer("Произошла ошибка при добавлении товара.")

@router.callback_query(lambda c: c.data == "admin_top")
async def admin_top(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    top_users = get_top_users()
    text = "🏆 Топ-10 пользователей:\n\n"
    for i, user in enumerate(top_users, start=1):
        text += f"{i}. {user[2] or user[1] or 'unknown'} — {user[3]} восьмерят (Ур. {user[4]})\n"
    await call.message.edit_text(text, reply_markup=back_to_main())
    await call.answer()

@router.callback_query(lambda c: c.data == "admin_history")
async def admin_history(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    history = get_request_history()
    if not history:
        await call.message.edit_text("Нет истории заявок.", reply_markup=back_to_main())
        return
    text = "📜 История заявок (последние 20):\n\n"
    for h in history:
        text += f"ID {h[0]} от @{h[2]}: {h[3]} — {h[4]}\n"
    await call.message.edit_text(text, reply_markup=back_to_main())
    await call.answer()

@router.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    
    stats = get_daily_stats()
    text = f"📊 Статистика за сегодня ({stats[0]}):\n\n"
    text += f"Заявок: {stats[2]}\n"
    text += f"Одобрено: {stats[3]}\n"
    text += f"Переводов: {stats[4]}\n"
    text += f"Всего переведено: {stats[5]} восьмерят"
    
    await call.message.edit_text(text, reply_markup=back_to_main())
    await call.answer()

@router.callback_query(lambda c: c.data == "admin_adjust_menu")
async def admin_adjust_menu(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="+8", callback_data="adjust_amount_8")
    builder.button(text="+40", callback_data="adjust_amount_40")
    builder.button(text="-8", callback_data="adjust_amount_neg_8")
    builder.button(text="-40", callback_data="adjust_amount_neg_40")
    builder.button(text="Другое", callback_data="adjust_custom")
    builder.button(text="👤 Показать профиль", callback_data="show_profile")
    builder.button(text=BACK_BUTTON, callback_data="back_to_main")
    
    await call.message.edit_text("Выберите действие:", reply_markup=builder.as_markup())
    await call.answer()

@router.callback_query(lambda c: c.data.startswith("adjust_amount_"))
async def admin_adjust_amount(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    amount_str = call.data.split("_")[2]
    if amount_str.startswith("neg_"):
        amount = -int(amount_str[4:])
    else:
        amount = int(amount_str)

    await call.message.edit_text(f"Вы выбрали: {'+' if amount > 0 else ''}{amount}\n\nТеперь введите:\n\n/adjust USER_ID {amount}")
    await call.answer()

@router.callback_query(lambda c: c.data == "adjust_custom")
async def admin_adjust_custom(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    await call.message.edit_text("Введите команду вручную:\n\n/adjust USER_ID КОЛИЧЕСТВО\n\n(положительное — выдать, отрицательное — снять)")
    await call.answer()

@router.callback_query(lambda c: c.data == "show_profile")
async def show_profile(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    await call.message.edit_text("Введите ID пользователя, чтобы посмотреть профиль:\n\nПример: /profile 123456789")
    await call.answer()

# === ФОНОВАЯ ЗАДАЧА: Напоминание о заявках ===
async def check_pending_requests():
    while True:
        requests = get_pending_requests()
        if requests:
            for admin_id in ADMINS:
                try:
                    text = "⏰ У вас есть необработанные заявки:\n"
                    for r in requests:
                        text += f"ID {r[0]} от {r[3] or r[2]}: {r[4]}\n"
                    await bot.send_message(admin_id, text)
                except Exception as e:
                    logging.error(f"Ошибка отправки напоминания админу {admin_id}: {e}")
        await asyncio.sleep(86400)  # 24 часа

# === ФОНОВАЯ ЗАДАЧА: Начисление процентов в банке ===
async def bank_interest_task():
    while True:
        cursor.execute("SELECT user_id, bank_balance FROM users WHERE bank_balance > 0")
        users = cursor.fetchall()
        
        for user_id, bank_balance in users:
            interest = int(bank_balance * 0.01)  # 1% в день
            if interest > 0:
                update_balance(user_id, interest, "", "", "")
                cursor.execute("UPDATE users SET bank_balance = bank_balance + ? WHERE user_id = ?", (interest, user_id))
        
        conn.commit()
        await asyncio.sleep(86400)  # 24 часа

async def main():
    dp.include_router(router)
    
    # Запуск фоновых задач
    loop = asyncio.get_event_loop()
    loop.create_task(check_pending_requests())
    loop.create_task(bank_interest_task())
    
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
