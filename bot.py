import sqlite3
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram import F
import asyncio

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("admin_actions.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Токен бота
BOT_TOKEN = "8504090327:AAEWPolM5Kb1uRbvJB7dWphbD9nYVzZJc9Q"
ADMINS = [8268613975]  # ЗАМЕНИТЕ НА СВОЙ ID

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Подключение к базе данных
conn = sqlite3.connect("blyamzic.db", check_same_thread=False)
cursor = conn.cursor()

# === КОНСТАНТЫ ===
BACK_BUTTON = "⬅️ Назад"
SQL_GET_USER_ID_BY_REQ_ID = "SELECT user_id FROM requests WHERE id = ?"
MSG_ONLY_IN_GROUP = "❌ Эта команда доступна только в группе."
MSG_ONLY_IN_PRIVATE = "❌ Команда доступна только в личных сообщениях."
MSG_ACCESS_DENIED = "❌ Доступ запрещён."
MSG_ONLY_IN_PRIVATE_ALERT = "❌ Команда доступна только в личных сообщениях."
MSG_ACCESS_DENIED_ALERT = "❌ Доступ запрещён."

# Создание/обновление таблиц
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 0
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        reason TEXT,
        media_id TEXT DEFAULT NULL,
        status TEXT DEFAULT 'pending',
        admin_id INTEGER DEFAULT NULL
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS shop (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        price INTEGER
    )
''')
conn.commit()

def get_user_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    return result[0] if result else 0

def update_balance(user_id, amount, username="unknown"):
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        new_balance = result[0] + amount
        cursor.execute("UPDATE users SET balance = ?, username = ? WHERE user_id = ?", (new_balance, username, user_id))
    else:
        cursor.execute("INSERT INTO users (user_id, username, balance) VALUES (?, ?, ?)", (user_id, username, amount))
    conn.commit()
    logging.info(f"ADJUST | User: {user_id} (@{username}) | Amount: {amount} | New: {get_user_balance(user_id)}")

def add_request(user_id, username, reason, media_id=None):
    cursor.execute("INSERT INTO requests (user_id, username, reason, media_id) VALUES (?, ?, ?, ?)", (user_id, username, reason, media_id))
    conn.commit()

def get_pending_requests():
    cursor.execute("SELECT id, user_id, username, reason, media_id FROM requests WHERE status = 'pending'")
    return cursor.fetchall()

def get_request_history(limit=20):
    cursor.execute("SELECT id, user_id, username, reason, status, admin_id FROM requests ORDER BY id DESC LIMIT ?", (limit,))
    return cursor.fetchall()

def update_request_status(req_id, status, admin_id):
    cursor.execute("UPDATE requests SET status = ?, admin_id = ? WHERE id = ?", (status, admin_id, req_id))
    if status == 'approved':
        cursor.execute(SQL_GET_USER_ID_BY_REQ_ID, (req_id,))
        user_id = cursor.fetchone()[0]
        update_balance(user_id, 10)
        logging.info(f"APPROVE | Request #{req_id} | User: {user_id} | Admin: {admin_id}")
    elif status == 'declined':
        cursor.execute(SQL_GET_USER_ID_BY_REQ_ID, (req_id,))
        user_id = cursor.fetchone()[0]
        logging.info(f"DECLINE | Request #{req_id} | User: {user_id} | Admin: {admin_id}")
    conn.commit()

def get_shop_items():
    cursor.execute("SELECT id, name, price FROM shop")
    return cursor.fetchall()

def add_item_to_shop(name, price):
    cursor.execute("INSERT INTO shop (name, price) VALUES (?, ?)", (name, price))
    conn.commit()

def get_top_users(limit=10):
    cursor.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,))
    return cursor.fetchall()

def buy_item_by_id(user_id, item_id):
    items = get_shop_items()
    item = next((i for i in items if i[0] == item_id), None)
    if not item:
        return False, "Товар не найден"
    price = item[2]
    balance = get_user_balance(user_id)
    if balance < price:
        return False, "Недостаточно блямзиков"
    update_balance(user_id, -price)
    return True, f"Вы купили {item[1]}!"

# === ПРОВЕРКИ ===

def is_private_chat(message: Message) -> bool:
    return message.chat.type == "private"

def is_group_chat(message: Message) -> bool:
    return message.chat.type in ["group", "supergroup"]

def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

# Назад в главное меню
def back_to_main():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=BACK_BUTTON, callback_data="back_to_main")]
    ])

# === ОБЩИЕ КОМАНДЫ (работают только в группе) ===

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("Привет! Это бот для блямзиков. Используй /balance, /apply_blyamzic, /shop.")

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    balance = get_user_balance(message.from_user.id)
    await message.answer(f"Ваш баланс: {balance} блямзиков.")

# === Команда /apply_blyamzic с поддержкой медиа ===
@dp.message(Command("apply_blyamzic"))
async def cmd_apply(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Используйте: /apply_blyamzic Причина получения")
        return
    reason = args[1]

    # Проверяем, есть ли медиа
    media_id = None
    if message.photo:
        media_id = message.photo[-1].file_id
    elif message.video:
        media_id = message.video.file_id
    elif message.document:
        media_id = message.document.file_id
    elif message.voice:
        media_id = message.voice.file_id
    elif message.audio:
        media_id = message.audio.file_id
    elif message.video_note:
        media_id = message.video_note.file_id

    add_request(message.from_user.id, message.from_user.username or "unknown", reason, media_id)
    await message.answer("Ваша заявка отправлена на проверку администратору.")

@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    items = get_shop_items()
    if not items:
        await message.answer("Магазин пуст.")
        return
    text = "🛍 Магазин блямзиков:\n\n"
    for item in items:
        text += f"{item[0]}. {item[1]} — {item[2]} блямзиков\n"  # ✅ Исправлено: было item[0}]
    text += "\nЧтобы купить, введите номер товара (ID)."
    await message.answer(text)

# === Обработка ввода номера товара для покупки ===
@dp.message(F.text.isdigit())
async def handle_number_input(message: Message):
    if not is_group_chat(message):
        return
    try:
        item_id = int(message.text)
        _, msg = buy_item_by_id(message.from_user.id, item_id)  # ✅ Заменено: success -> _
        await message.answer(msg)
    except Exception:
        await message.answer("Неверный формат. Введите номер товара из /shop.")

@dp.message(Command("top"))
async def cmd_top(message: Message):
    if not is_group_chat(message):
        await message.answer(MSG_ONLY_IN_GROUP)
        return
    top_users = get_top_users()
    if not top_users:
        await message.answer("Нет данных для топа.")
        return
    text = "🏆 Топ-10 по блямзикам:\n\n"
    for i, user in enumerate(top_users, start=1):
        text += f"{i}. @{user[1] or 'unknown'} — {user[2]} блямзиков\n"
    await message.answer(text)

# === АДМИН-КОМАНДЫ (работают только в ЛС) ===

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_private_chat(message):
        await message.answer(MSG_ONLY_IN_PRIVATE)
        return
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ACCESS_DENIED)
        return

    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📋 Заявки", callback_data="admin_requests")],
        [types.InlineKeyboardButton(text="🛒 Магазин", callback_data="admin_shop")],
        [types.InlineKeyboardButton(text="👥 Топ", callback_data="admin_top")],
        [types.InlineKeyboardButton(text="📜 История", callback_data="admin_history")],
        [types.InlineKeyboardButton(text="💰 Выдать/списать", callback_data="admin_adjust_menu")],
    ])
    await message.answer("Админ-панель:", reply_markup=keyboard)

@dp.message(Command("adjust"))
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
        cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            await message.answer(f"❌ Пользователь с ID {user_id} не найден. Убедитесь, что он хотя бы раз написал боту.")
            return

        username = user[0]
        update_balance(user_id, amount, username)
        action = "начислено" if amount > 0 else "снято"
        await message.answer(f"✅ {abs(amount)} блямзиков {action} пользователю @{username} (ID: {user_id}).")
        try:
            await bot.send_message(user_id, f"🔔 Админ {action} {abs(amount)} блямзиков. Новое значение: {get_user_balance(user_id)}")
        except Exception:
            pass
    except ValueError:
        await message.answer("Используйте: /adjust USER_ID КОЛИЧЕСТВО\n(например: /adjust 123456789 50)")
    except Exception as e:
        logging.error(f"Ошибка в /adjust: {e}")
        await message.answer("❌ Произошла ошибка. Проверьте логи.")

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
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
        cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            await message.answer("Пользователь не найден.")
            return
        username = user[0]
        cursor.execute("SELECT COUNT(*) FROM requests WHERE user_id = ?", (user_id,))
        total_requests = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM requests WHERE user_id = ? AND status = 'approved'", (user_id,))
        approved = cursor.fetchone()[0]
        await message.answer(
            f"👤 Профиль @{username} (ID: {user_id})\n"
            f"💰 Баланс: {balance} блямзиков\n"
            f"📊 Заявок всего: {total_requests}\n"
            f"✅ Одобрено: {approved}"
        )
    except ValueError:
        await message.answer("Неверный ID.")

# === АДМИН-ПАНЕЛЬ (все callback-функции тоже проверяют админа и ЛС) ===

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_menu(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📋 Заявки", callback_data="admin_requests")],
        [types.InlineKeyboardButton(text="🛒 Магазин", callback_data="admin_shop")],
        [types.InlineKeyboardButton(text="👥 Топ", callback_data="admin_top")],
        [types.InlineKeyboardButton(text="📜 История", callback_data="admin_history")],
        [types.InlineKeyboardButton(text="💰 Выдать/списать", callback_data="admin_adjust_menu")],
    ])
    await call.message.edit_text("Админ-панель:", reply_markup=keyboard)
    await call.answer()

@dp.callback_query(F.data == "admin_requests")
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
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    for r in requests:
        text += f"ID {r[0]} от @{r[2]}: {r[3]}\n"
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(text=f"✅ Одобрить #{r[0]}", callback_data=f"approve_{r[0]}"),
            types.InlineKeyboardButton(text=f"❌ Отклонить #{r[0]}", callback_data=f"decline_{r[0]}")
        ])
    keyboard.inline_keyboard.append([types.InlineKeyboardButton(text=BACK_BUTTON, callback_data="back_to_main")])
    await call.message.edit_text(text, reply_markup=keyboard)
    await call.answer()

# === Отправка медиа админу при одобрении/отклонении ===

async def send_media_to_admin(req_id, user_id, reason, media_id, admin_id, action):
    try:
        # Получаем юзернейм
        user = await bot.get_chat(user_id)
        username = user.username or "unknown"

        # Если есть медиа, отправляем его
        if media_id:
            await send_media_by_type(media_id, admin_id, req_id, username, reason, action)
        else:
            await bot.send_message(chat_id=admin_id, text=f"Заявка #{req_id} от @{username}\nПричина: {reason}\nДействие: {action}")
    except Exception as e:
        logging.error(f"Ошибка при отправке медиа админу {admin_id}: {e}")

async def send_media_by_type(media_id, admin_id, req_id, username, reason, action):
    caption = f"Заявка #{req_id} от @{username}\nПричина: {reason}\nДействие: {action}"
    # Список типов медиа и соответствующих методов
    media_types = [
        ("photo", "send_photo"),
        ("video", "send_video"),
        ("document", "send_document"),
        ("voice", "send_voice"),
        ("audio", "send_audio"),
        ("video_note", "send_video_note"),
    ]

    for media_type, method_name in media_types:
        try:
            method = getattr(bot, method_name)
            await method(chat_id=admin_id, **{media_type: media_id}, caption=caption)
            return
        except Exception:
            continue

    # Если не получилось — просто текст
    await bot.send_message(chat_id=admin_id, text=f"Заявка #{req_id} от @{username}\nПричина: {reason}\nДействие: {action}")

async def get_user_id_by_req_id(req_id):
    cursor.execute(SQL_GET_USER_ID_BY_REQ_ID, (req_id,))
    result = cursor.fetchone()
    return result[0] if result else None

@dp.callback_query(F.data.startswith("approve_"))
async def approve_request(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    req_id = int(call.data.split("_")[1])
    cursor.execute("SELECT user_id, reason, media_id FROM requests WHERE id = ?", (req_id,))
    row = cursor.fetchone()
    if not row:
        await call.answer("Заявка не найдена.", show_alert=True)
        return
    user_id, reason, media_id = row

    update_request_status(req_id, 'approved', call.from_user.id)

    try:
        await bot.send_message(user_id, f"✅ Ваша заявка #{req_id} одобрена! 10 блямзиков зачислено.")
    except Exception:
        pass

    await send_media_to_admin(req_id, user_id, reason, media_id, call.from_user.id, "✅ Одобрено")
    await admin_requests(call)

@dp.callback_query(F.data.startswith("decline_"))
async def decline_request(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    req_id = int(call.data.split("_")[1])
    cursor.execute("SELECT user_id, reason, media_id FROM requests WHERE id = ?", (req_id,))
    row = cursor.fetchone()
    if not row:
        await call.answer("Заявка не найдена.", show_alert=True)
        return
    user_id, reason, media_id = row

    update_request_status(req_id, 'declined', call.from_user.id)

    try:
        await bot.send_message(user_id, f"❌ Ваша заявка #{req_id} отклонена администратором.")
    except Exception:
        pass

    await send_media_to_admin(req_id, user_id, reason, media_id, call.from_user.id, "❌ Отклонено")
    await admin_requests(call)

@dp.callback_query(F.data == "admin_shop")
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
        text += f"{item[0]}. {item[1]} — {item[2]} блямзиков\n"
    text += "\nЧтобы добавить товар, нажмите кнопку ниже."
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_add_item_prompt")],
        [types.InlineKeyboardButton(text=BACK_BUTTON, callback_data="back_to_main")]
    ])
    await call.message.edit_text(text, reply_markup=keyboard)
    await call.answer()

@dp.callback_query(F.data == "admin_add_item_prompt")
async def admin_add_item_prompt(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    await call.message.edit_text("Введите название товара и цену в формате:\n\nНазвание Цена")
    await call.answer()

# === Обработка добавления товара через чат ===
@dp.message(F.text.regexp(r"^[^0-9].+ \d+$"))
async def handle_add_item(message: Message):
    if not is_private_chat(message):
        return
    if not is_admin(message.from_user.id):
        await message.answer(MSG_ACCESS_DENIED)
        return
    try:
        parts = message.text.rsplit(" ", 1)
        name = parts[0].strip()
        price = int(parts[1])
        add_item_to_shop(name, price)
        await message.answer(f"Товар '{name}' добавлен в магазин за {price} блямзиков.")
    except ValueError:
        await message.answer("Неверный формат. Введите: Название Цена")
    except Exception:
        await message.answer("Произошла ошибка при добавлении товара.")

@dp.callback_query(F.data == "admin_top")
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
        text += f"{i}. @{user[1] or 'unknown'} — {user[2]} блямзиков\n"
    await call.message.edit_text(text, reply_markup=back_to_main())
    await call.answer()

@dp.callback_query(F.data == "admin_history")
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

@dp.callback_query(F.data == "admin_adjust_menu")
async def admin_adjust_menu(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="+10", callback_data="adjust_amount_10")],
        [types.InlineKeyboardButton(text="+50", callback_data="adjust_amount_50")],
        [types.InlineKeyboardButton(text="-10", callback_data="adjust_amount_neg_10")],
        [types.InlineKeyboardButton(text="-50", callback_data="adjust_amount_neg_50")],
        [types.InlineKeyboardButton(text="Другое", callback_data="adjust_custom")],
        [types.InlineKeyboardButton(text="👤 Показать профиль", callback_data="show_profile")],
        [types.InlineKeyboardButton(text=BACK_BUTTON, callback_data="back_to_main")]
    ])
    await call.message.edit_text("Выберите действие:", reply_markup=keyboard)
    await call.answer()

@dp.callback_query(F.data.startswith("adjust_amount_"))
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

@dp.callback_query(F.data == "adjust_custom")
async def admin_adjust_custom(call: CallbackQuery):
    if not is_private_chat(call.message):
        await call.answer(MSG_ONLY_IN_PRIVATE_ALERT, show_alert=True)
        return
    if not is_admin(call.from_user.id):
        await call.answer(MSG_ACCESS_DENIED_ALERT, show_alert=True)
        return
    await call.message.edit_text("Введите команду вручную:\n\n/adjust USER_ID КОЛИЧЕСТВО\n\n(положительное — выдать, отрицательное — снять)")
    await call.answer()

@dp.callback_query(F.data == "show_profile")
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
async def check_pending_requests():  # noqa: S7503
    while True:
        requests = get_pending_requests()
        if requests:
            for admin_id in ADMINS:
                try:
                    text = "⏰ У вас есть необработанные заявки:\n"
                    for r in requests:
                        text += f"ID {r[0]} от @{r[2]}: {r[3]}\n"
                    await bot.send_message(admin_id, text)
                except Exception as e:
                    logging.error(f"Ошибка отправки напоминания админу {admin_id}: {e}")
        await asyncio.sleep(86400)  # 24 часа

if __name__ == "__main__":
    # Запуск фоновой задачи
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(check_pending_requests())
    # Запуск бота
    loop.run_until_complete(dp.start_polling(bot))