import sqlite3
import random
import logging
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler
)

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('vosemyata.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- КОНСТАНТЫ ---
BOT_TOKEN = '8537096347:AAHjr5TsYwKT5e75oP-mT7gdnJV3vSSQvEk'
ADMINS = [5171361978, 8268613975, 2143824530]
START_BALANCE = 100
WORK_COOLDOWN = 600
WORK2_COOLDOWN = 1800
WORK3_COOLDOWN = 3600
WORK4_COOLDOWN = 7200
TRANSFER_LIMIT_PER_USER = 3
PROMOCODE_REWARD = 50
WEEKLY_REWARD_BASE = 50
WEEKLY_REWARD_PER_LEVEL = 5
DAILY_BANK_INTEREST_RATE = 0.01

# --- СОСТОЯНИЯ FSM ---
(
    CREATE_PROMO_REWARD,
    CREATE_PROMO_USES,
    CREATE_PROMO_EXPIRES,
    DELETE_PROMO_CODE,
    ADD_ITEM_NAME,
    ADD_ITEM_PRICE,
    ADD_ITEM_DESC,
    DELETE_ITEM_ID,
    ADMIN_ADJUST_INPUT
) = range(9)

# --- ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ ---
conn = sqlite3.connect('vosemyata.db', check_same_thread=False)
cursor = conn.cursor()

# --- СОЗДАНИЕ ТАБЛИЦ ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    bank_balance INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    exp INTEGER DEFAULT 0,
    last_work_time REAL,
    last_work2_time REAL,
    last_work3_time REAL,
    last_work4_time REAL,
    daily_bank_interest_time REAL,
    weekly_claimed_date TEXT,
    transfers_today TEXT DEFAULT '{}',
    profile_description TEXT DEFAULT 'Нет описания',
    profile_skin TEXT DEFAULT 'обычный'
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS promocodes (
    code TEXT PRIMARY KEY,
    reward INTEGER,
    uses_limit INTEGER,
    uses_count INTEGER DEFAULT 0,
    creator_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS used_promocodes (
    user_id INTEGER,
    code TEXT,
    used_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, code)
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS shop_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    description TEXT
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS applications (
    app_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    first_name TEXT,
    reason TEXT,
    status TEXT DEFAULT 'pending',
    admin_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS games (
    game_id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    date TEXT DEFAULT CURRENT_TIMESTAMP
)
''')
conn.commit()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_user_data(user_id, effective_user=None):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        try:
            transfers_today = json.loads(result[12]) if result[12] else {}
        except:
            transfers_today = {}
        user = {
            'user_id': result[0],
            'username': result[1],
            'balance': result[2],
            'bank_balance': result[3],
            'level': result[4],
            'exp': result[5],
            'last_work_time': result[6] or 0,
            'last_work2_time': result[7] or 0,
            'last_work3_time': result[8] or 0,
            'last_work4_time': result[9] or 0,
            'daily_bank_interest_time': result[10] or 0,
            'weekly_claimed_date': result[11],
            'transfers_today': transfers_today,
            'profile_description': result[13],
            'profile_skin': result[14]
        }
        if effective_user and effective_user.username != user['username']:
            update_user_data(user_id, username=effective_user.username)
            user['username'] = effective_user.username
        return user
    else:
        username = effective_user.username if effective_user else ''
        new_user = {
            'user_id': user_id,
            'username': username,
            'balance': START_BALANCE,
            'bank_balance': 0,
            'level': 1,
            'exp': 0,
            'last_work_time': 0,
            'last_work2_time': 0,
            'last_work3_time': 0,
            'last_work4_time': 0,
            'daily_bank_interest_time': 0,
            'weekly_claimed_date': None,
            'transfers_today': {},
            'profile_description': 'Нет описания',
            'profile_skin': 'обычный'
        }
        cursor.execute(
            "INSERT INTO users (user_id, username, balance, level, exp, profile_description, profile_skin) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, new_user['balance'], new_user['level'], new_user['exp'], new_user['profile_description'], new_user['profile_skin'])
        )
        conn.commit()
        return new_user

def update_user_data(user_id, **kwargs):
    allowed_fields = {
        'username', 'balance', 'bank_balance', 'level', 'exp',
        'last_work_time', 'last_work2_time', 'last_work3_time', 'last_work4_time',
        'daily_bank_interest_time', 'weekly_claimed_date', 'transfers_today',
        'profile_description', 'profile_skin'
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not fields:
        return
    set_clause = ", ".join([f"{key} = ?" for key in fields])
    values = list(fields.values()) + [user_id]
    cursor.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
    conn.commit()

def add_exp(user_id, exp):
    user = get_user_data(user_id)
    new_exp = user['exp'] + exp
    level_up = 0
    while new_exp >= user['level'] * 100:
        new_exp -= user['level'] * 100
        level_up += 1
    new_level = user['level'] + level_up
    update_user_data(user_id, exp=new_exp, level=new_level)
    return new_level, new_exp


# --- ОСНОВНЫЕ КОМАНДЫ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🎮 Игры и развлечения:
/dice <ставка> — Игра в кости. 4-6 — выиграл (ставка x2).
/black_red <ставка> <red/black> — Рулетка. Выигрыш x2.
/ladder <ставка> — Лесенка: 1-2 (x3), 3-5 (x2), 6 (проигрыш).
/rank — Уровень и опыт.
💰 Финансы:
/balance — Баланс, уровень, статистика.
/bank — Управление банком.
/deposit <сумма> — Положить в банк.
/withdraw <сумма> — Снять из банка.
/transfer @username <сумма> — Перевести пользователю.
/gift @username <сумма> <сообщение> — Подарить с сообщением.
/top — Топ-10 по восьмерятам.
📦 Магазин:
/shop — Посмотреть магазин.
/buy <ID> — Купить товар.
🎁 Заработок:
/weekly — Еженедельная награда.
/work — 1–5 восьмерят (раз в 10 мин).
/work2 — 3–8 восьмерят (раз в 30 мин).
/work3 — 5–15 восьмерят (раз в 1 час).
/work4 — 10–25 восьмерят (раз в 2 часа).
/apply_vosemyata <причина> — Подать заявку на восьмеряты.
🎟️ Промокоды:
/use_promocode <код> — Ввести промокод.
/create_promocode — Только админ.
/delete_promocode — Только админ.
📊 Профиль:
/profile — Свой профиль.
/setskin <скин> — Установить скин.
/setdesc <описание> — Установить описание.
/stats — Статистика.
📞 Обратная связь:
/feedback <сообщение> — Отзыв.
/bug_report <сообщение> — Ошибка.
/suggest <сообщение> — Предложение.
👑 Админ-панель:
/admin — Открыть панель (админ).
"""
    await update.message.reply_text(help_text, disable_notification=True)

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user_data(update.effective_user.id, update.effective_user)
    msg = f"""
💰 Баланс: {user['balance']} восьмерят
🏦 В банке: {user['bank_balance']} восьмерят
🏆 Уровень: {user['level']}
⚡ Опыт: {user['exp']}
"""
    await update.message.reply_text(msg, disable_notification=True)

# --- ИГРЫ ---
async def dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /dice <ставка>", disable_notification=True)
        return
    try:
        bet = int(args[0])
    except ValueError:
        await update.message.reply_text("Ставка должна быть числом.", disable_notification=True)
        return
    user = get_user_data(update.effective_user.id, update.effective_user)
    if bet <= 0:
        await update.message.reply_text("Ставка должна быть больше 0.", disable_notification=True)
        return
    if user['balance'] < bet:
        await update.message.reply_text("❌ Недостаточно восьмерят.", disable_notification=True)
        return
    roll = random.randint(1, 6)
    if roll >= 4:
        win_amount = bet * 2
        user['balance'] += win_amount
        msg = f"🎲 Кубик: {roll}. 🎉 Вы выиграли {win_amount} восьмерят!"
        result = win_amount - bet
    else:
        user['balance'] -= bet
        msg = f"🎲 Кубик: {roll}. 💀 Вы проиграли {bet} восьмерят."
        result = -bet
    update_user_data(update.effective_user.id, balance=user['balance'])
    cursor.execute("INSERT INTO games (user_id, game_type, bet, result) VALUES (?, ?, ?, ?)",
                   (update.effective_user.id, 'dice', bet, result))
    conn.commit()
    await update.message.reply_text(msg, disable_notification=True)

async def black_red(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Используйте: /black_red <ставка> <red/black>", disable_notification=True)
        return
    try:
        bet = int(args[0])
    except ValueError:
        await update.message.reply_text("Ставка должна быть числом.", disable_notification=True)
        return
    color = args[1].lower()
    if color not in ['red', 'black']:
        await update.message.reply_text("Цвет должен быть 'red' или 'black'.", disable_notification=True)
        return
    user = get_user_data(update.effective_user.id, update.effective_user)
    if bet <= 0:
        await update.message.reply_text("Ставка должна быть больше 0.", disable_notification=True)
        return
    if user['balance'] < bet:
        await update.message.reply_text("❌ Недостаточно восьмерят.", disable_notification=True)
        return
    win_color = random.choice(['red', 'black'])
    if win_color == color:
        win_amount = bet * 2
        user['balance'] += win_amount
        msg = f"🎰 Выпал {win_color}. 🎉 Вы выиграли {win_amount} восьмерят!"
        result = win_amount - bet
    else:
        user['balance'] -= bet
        msg = f"🎰 Выпал {win_color}. 💀 Вы проиграли {bet} восьмерят."
        result = -bet
    update_user_data(update.effective_user.id, balance=user['balance'])
    cursor.execute("INSERT INTO games (user_id, game_type, bet, result) VALUES (?, ?, ?, ?)",
                   (update.effective_user.id, 'black_red', bet, result))
    conn.commit()
    await update.message.reply_text(msg, disable_notification=True)

async def ladder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /ladder <ставка>", disable_notification=True)
        return
    try:
        bet = int(args[0])
    except ValueError:
        await update.message.reply_text("Ставка должна быть числом.", disable_notification=True)
        return
    user = get_user_data(update.effective_user.id, update.effective_user)
    if bet <= 0:
        await update.message.reply_text("Ставка должна быть больше 0.", disable_notification=True)
        return
    if user['balance'] < bet:
        await update.message.reply_text("❌ Недостаточно восьмерят.", disable_notification=True)
        return
    roll = random.randint(1, 6)
    if roll in [1, 2]:
        win_amount = bet * 3
        user['balance'] += win_amount
        msg = f"🪜 Лесенка: {roll}. 🎉 Вы выиграли {win_amount} восьмерят! (x3)"
        result = win_amount - bet
    elif roll in [3, 4, 5]:
        win_amount = bet * 2
        user['balance'] += win_amount
        msg = f"🪜 Лесенка: {roll}. 🎉 Вы выиграли {win_amount} восьмерят! (x2)"
        result = win_amount - bet
    else:
        user['balance'] -= bet
        msg = f"🪜 Лесенка: {roll}. 💀 Вы проиграли {bet} восьмерят."
        result = -bet
    update_user_data(update.effective_user.id, balance=user['balance'])
    cursor.execute("INSERT INTO games (user_id, game_type, bet, result) VALUES (?, ?, ?, ?)",
                   (update.effective_user.id, 'ladder', bet, result))
    conn.commit()
    await update.message.reply_text(msg, disable_notification=True)

async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user_data(update.effective_user.id, update.effective_user)
    msg = f"🏆 Ваш уровень: {user['level']}\n⚡ Опыт: {user['exp']}"
    await update.message.reply_text(msg, disable_notification=True)

# --- РАБОТА ---
async def work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    user = get_user_data(update.effective_user.id, update.effective_user)
    now = datetime.now().timestamp()
    if now - user['last_work_time'] < WORK_COOLDOWN:
        remaining = WORK_COOLDOWN - (now - user['last_work_time'])
        minutes, seconds = divmod(int(remaining), 60)
        await update.message.reply_text(f"⏰ Подождите еще {minutes} мин {seconds} сек.", disable_notification=True)
        return
    earnings = random.randint(1, 5)
    user['balance'] += earnings
    update_user_data(update.effective_user.id, balance=user['balance'], last_work_time=now)
    add_exp(update.effective_user.id, 1)
    await update.message.reply_text(f"💼 Вы заработали {earnings} восьмерят!", disable_notification=True)

async def work2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    user = get_user_data(update.effective_user.id, update.effective_user)
    now = datetime.now().timestamp()
    if now - user['last_work2_time'] < WORK2_COOLDOWN:
        remaining = WORK2_COOLDOWN - (now - user['last_work2_time'])
        minutes, seconds = divmod(int(remaining), 60)
        await update.message.reply_text(f"⏰ Подождите еще {minutes} мин {seconds} сек.", disable_notification=True)
        return
    earnings = random.randint(3, 8)
    user['balance'] += earnings
    update_user_data(update.effective_user.id, balance=user['balance'], last_work2_time=now)
    add_exp(update.effective_user.id, 2)
    await update.message.reply_text(f"💼 Вы заработали {earnings} восьмерят!", disable_notification=True)

async def work3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    user = get_user_data(update.effective_user.id, update.effective_user)
    now = datetime.now().timestamp()
    if now - user['last_work3_time'] < WORK3_COOLDOWN:
        remaining = WORK3_COOLDOWN - (now - user['last_work3_time'])
        minutes, seconds = divmod(int(remaining), 60)
        await update.message.reply_text(f"⏰ Подождите еще {minutes} мин {seconds} сек.", disable_notification=True)
        return
    earnings = random.randint(5, 15)
    user['balance'] += earnings
    update_user_data(update.effective_user.id, balance=user['balance'], last_work3_time=now)
    add_exp(update.effective_user.id, 3)
    await update.message.reply_text(f"💼 Вы заработали {earnings} восьмерят!", disable_notification=True)

async def work4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    user = get_user_data(update.effective_user.id, update.effective_user)
    now = datetime.now().timestamp()
    if now - user['last_work4_time'] < WORK4_COOLDOWN:
        remaining = WORK4_COOLDOWN - (now - user['last_work4_time'])
        minutes, seconds = divmod(int(remaining), 60)
        await update.message.reply_text(f"⏰ Подождите еще {minutes} мин {seconds} сек.", disable_notification=True)
        return
    earnings = random.randint(10, 25)
    user['balance'] += earnings
    update_user_data(update.effective_user.id, balance=user['balance'], last_work4_time=now)
    add_exp(update.effective_user.id, 5)
    await update.message.reply_text(f"💼 Вы заработали {earnings} восьмерят!", disable_notification=True)

# --- ЕЖЕНЕДЕЛЬНАЯ НАГРАДА ---
async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    user = get_user_data(update.effective_user.id, update.effective_user)
    today = datetime.now().strftime('%Y-%m-%d')
    if user['weekly_claimed_date'] == today:
        await update.message.reply_text("❌ Вы уже забрали недельную награду сегодня.", disable_notification=True)
        return
    reward = WEEKLY_REWARD_BASE + (user['level'] * WEEKLY_REWARD_PER_LEVEL)
    user['balance'] += reward
    update_user_data(update.effective_user.id, balance=user['balance'], weekly_claimed_date=today)
    await update.message.reply_text(f"🎁 Вы получили {reward} восьмерят за неделю!", disable_notification=True)

# --- БАНК ---
async def bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user_data(update.effective_user.id, update.effective_user)
    msg = f"""
🏦 Баланс: {user['balance']} восьмерят
💰 В банке: {user['bank_balance']} восьмерят
📈 Проценты: {int(user['bank_balance'] * DAILY_BANK_INTEREST_RATE)} в день
"""
    keyboard = [
        [InlineKeyboardButton("💰 Положить", callback_data="bank_deposit_prompt"),
         InlineKeyboardButton("💸 Снять", callback_data="bank_withdraw_prompt")],
        [InlineKeyboardButton("📊 Инфо", callback_data="bank_info")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(msg, reply_markup=reply_markup, disable_notification=True)

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /deposit <сумма>", disable_notification=True)
        return
    try:
        amount = int(args[0])
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.", disable_notification=True)
        return
    user = get_user_data(update.effective_user.id, update.effective_user)
    if amount <= 0:
        await update.message.reply_text("Сумма должна быть больше 0.", disable_notification=True)
        return
    if user['balance'] < amount:
        await update.message.reply_text("❌ Недостаточно восьмерят.", disable_notification=True)
        return
    user['balance'] -= amount
    user['bank_balance'] += amount
    update_user_data(update.effective_user.id, balance=user['balance'], bank_balance=user['bank_balance'])
    await update.message.reply_text(f"✅ Вы положили {amount} восьмерят в банк.", disable_notification=True)

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /withdraw <сумма>", disable_notification=True)
        return
    try:
        amount = int(args[0])
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.", disable_notification=True)
        return
    user = get_user_data(update.effective_user.id, update.effective_user)
    if amount <= 0:
        await update.message.reply_text("Сумма должна быть больше 0.", disable_notification=True)
        return
    if user['bank_balance'] < amount:
        await update.message.reply_text("❌ Недостаточно восьмерят в банке.", disable_notification=True)
        return
    user['balance'] += amount
    user['bank_balance'] -= amount
    update_user_data(update.effective_user.id, balance=user['balance'], bank_balance=user['bank_balance'])
    await update.message.reply_text(f"✅ Вы сняли {amount} восьмерят из банка.", disable_notification=True)

# --- ПЕРЕВОДЫ ---
async def transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Перевод возможен только в группе.", disable_notification=True)
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Используйте: /transfer @username <сумма>", disable_notification=True)
        return
    try:
        target_username = args[0].replace('@', '')
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.", disable_notification=True)
        return
    if amount <= 0:
        await update.message.reply_text("Сумма должна быть больше 0.", disable_notification=True)
        return
    cursor.execute("SELECT user_id FROM users WHERE username = ?", (target_username,))
    target_row = cursor.fetchone()
    if not target_row:
        await update.message.reply_text("❌ Пользователь не найден.", disable_notification=True)
        return
    target_id = target_row[0]
    sender = get_user_data(update.effective_user.id, update.effective_user)
    if sender['balance'] < amount:
        await update.message.reply_text("❌ Недостаточно восьмерят.", disable_notification=True)
        return
    transfers_today = sender['transfers_today']
    if str(target_id) in transfers_today:
        if transfers_today[str(target_id)] >= TRANSFER_LIMIT_PER_USER:
            await update.message.reply_text(f"❌ Вы уже перевели 3 раза этому пользователю сегодня.", disable_notification=True)
            return
        transfers_today[str(target_id)] += 1
    else:
        transfers_today[str(target_id)] = 1
    sender['balance'] -= amount
    update_user_data(update.effective_user.id, balance=sender['balance'], transfers_today=json.dumps(transfers_today))
    target_user = get_user_data(target_id)
    target_user['balance'] += amount
    update_user_data(target_id, balance=target_user['balance'])
    await update.message.reply_text(f"✅ Вы перевели {amount} восьмерят пользователю @{target_username}.", disable_notification=True)

async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Подарок возможен только в группе.", disable_notification=True)
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Используйте: /gift @username <сумма> <сообщение>", disable_notification=True)
        return
    try:
        target_username = args[0].replace('@', '')
        amount = int(args[1])
        message = ' '.join(args[2:])
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом.", disable_notification=True)
        return
    if amount <= 0:
        await update.message.reply_text("Сумма должна быть больше 0.", disable_notification=True)
        return
    cursor.execute("SELECT user_id FROM users WHERE username = ?", (target_username,))
    target_row = cursor.fetchone()
    if not target_row:
        await update.message.reply_text("❌ Пользователь не найден.", disable_notification=True)
        return
    target_id = target_row[0]
    sender = get_user_data(update.effective_user.id, update.effective_user)
    if sender['balance'] < amount:
        await update.message.reply_text("❌ Недостаточно восьмерят.", disable_notification=True)
        return
    sender['balance'] -= amount
    update_user_data(update.effective_user.id, balance=sender['balance'])
    target_user = get_user_data(target_id)
    target_user['balance'] += amount
    update_user_data(target_id, balance=target_user['balance'])
    await update.message.reply_text(f"🎁 Вы подарили {amount} восьмерят пользователю @{target_username} с сообщением: {message}", disable_notification=True)

# --- ТОП, МАГАЗИН, ПРОФИЛЬ ---
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT username, balance, level FROM users ORDER BY balance DESC LIMIT 10")
    rows = cursor.fetchall()
    top_list = "\n".join([f"{i+1}. @{row[0] or 'noname'} — {row[1]} (Ур. {row[2]})" for i, row in enumerate(rows)])
    await update.message.reply_text(f"🏆 Топ-10:\n{top_list or 'Пусто'}", disable_notification=True)

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT item_id, name, price, description FROM shop_items")
    items = cursor.fetchall()
    if not items:
        await update.message.reply_text("🛍️ Магазин пуст.", disable_notification=True)
        return
    shop_list = "\n".join([f"ID: {item[0]} | {item[1]} — {item[2]} восьмерят\n{item[3] or ''}" for item in items])
    await update.message.reply_text(f"🛍️ Магазин:\n{shop_list}", disable_notification=True)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /buy <ID_товара>", disable_notification=True)
        return
    try:
        item_id = int(args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.", disable_notification=True)
        return
    cursor.execute("SELECT name, price FROM shop_items WHERE item_id = ?", (item_id,))
    item = cursor.fetchone()
    if not item:
        await update.message.reply_text("❌ Товар не найден.", disable_notification=True)
        return
    name, price = item
    user = get_user_data(update.effective_user.id, update.effective_user)
    if user['balance'] < price:
        await update.message.reply_text("❌ Недостаточно восьмерят.", disable_notification=True)
        return
    user['balance'] -= price
    update_user_data(update.effective_user.id, balance=user['balance'])
    await update.message.reply_text(f"✅ Вы купили {name} за {price} восьмерят.", disable_notification=True)

async def use_promocode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        await update.message.reply_text("❌ Использовать промокод можно только в личке.", disable_notification=True)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /use_promocode <код>", disable_notification=True)
        return
    code = args[0]
    cursor.execute("SELECT reward, uses_limit, uses_count, expires_at FROM promocodes WHERE code = ?", (code,))
    result = cursor.fetchone()
    if not result:
        await update.message.reply_text("❌ Неверный промокод.", disable_notification=True)
        return
    reward, uses_limit, uses_count, expires_at = result
    if expires_at and datetime.fromisoformat(expires_at) < datetime.now():
        await update.message.reply_text("❌ Срок действия промокода истёк.", disable_notification=True)
        return
    if uses_count >= uses_limit:
        await update.message.reply_text("❌ Лимит использований промокода исчерпан.", disable_notification=True)
        return
    user_id = update.effective_user.id
    cursor.execute("SELECT 1 FROM used_promocodes WHERE user_id = ? AND code = ?", (user_id, code))
    if cursor.fetchone():
        await update.message.reply_text("❌ Вы уже использовали этот промокод.", disable_notification=True)
        return
    user = get_user_data(user_id, update.effective_user)
    user['balance'] += reward
    update_user_data(user_id, balance=user['balance'])
    cursor.execute("UPDATE promocodes SET uses_count = uses_count + 1 WHERE code = ?", (code,))
    cursor.execute("INSERT INTO used_promocodes (user_id, code) VALUES (?, ?)", (user_id, code))
    conn.commit()
    await update.message.reply_text(f"🎉 Вы получили {reward} восьмерят по промокоду!", disable_notification=True)

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user_data(update.effective_user.id, update.effective_user)
    msg = f"""
👤 Профиль:
Имя: {update.effective_user.first_name or 'Не указано'}
Username: @{user['username'] or 'не задан'}
💰 Баланс: {user['balance']}
🏆 Уровень: {user['level']}
📝 Описание: {user['profile_description']}
🎨 Скин: {user['profile_skin']}
"""
    await update.message.reply_text(msg, disable_notification=True)

async def setskin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /setskin <название_скина>", disable_notification=True)
        return
    skin = args[0]
    update_user_data(update.effective_user.id, profile_skin=skin)
    await update.message.reply_text(f"🎨 Скин изменён на '{skin}'.", disable_notification=True)

async def setdesc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /setdesc <описание>", disable_notification=True)
        return
    desc = ' '.join(args)
    update_user_data(update.effective_user.id, profile_description=desc)
    await update.message.reply_text(f"📝 Описание установлено: {desc}", disable_notification=True)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user_data(update.effective_user.id, update.effective_user)
    msg = f"""
📊 Ваша статистика:
Уровень: {user['level']}
Опыт: {user['exp']}
Баланс: {user['balance']}
В банке: {user['bank_balance']}
"""
    await update.message.reply_text(msg, disable_notification=True)

# --- ОБРАТНАЯ СВЯЗЬ ---
async def feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        await update.message.reply_text("❌ Отзыв можно отправить только в личке.", disable_notification=True)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /feedback <сообщение>", disable_notification=True)
        return
    message = ' '.join(args)
    cursor.execute("INSERT INTO feedback (user_id, type, message) VALUES (?, 'feedback', ?)", (update.effective_user.id, message))
    conn.commit()
    await update.message.reply_text("✅ Спасибо за ваш отзыв!", disable_notification=True)

async def bug_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        await update.message.reply_text("❌ Сообщение об ошибке можно отправить только в личке.", disable_notification=True)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /bug_report <сообщение>", disable_notification=True)
        return
    message = ' '.join(args)
    cursor.execute("INSERT INTO feedback (user_id, type, message) VALUES (?, 'bug', ?)", (update.effective_user.id, message))
    conn.commit()
    await update.message.reply_text("✅ Спасибо за сообщение об ошибке!", disable_notification=True)

async def suggest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        await update.message.reply_text("❌ Предложение можно отправить только в личке.", disable_notification=True)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /suggest <сообщение>", disable_notification=True)
        return
    message = ' '.join(args)
    cursor.execute("INSERT INTO feedback (user_id, type, message) VALUES (?, 'suggestion', ?)", (update.effective_user.id, message))
    conn.commit()
    await update.message.reply_text("✅ Спасибо за ваше предложение!", disable_notification=True)

# --- АДМИН-ПАНЕЛЬ ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("❌ У вас нет прав администратора.", disable_notification=True)
        return
    keyboard = [
        [InlineKeyboardButton("📋 Заявки", callback_data="admin_applications")],
        [InlineKeyboardButton("🏷️ Промокоды", callback_data="admin_promocodes")],
        [InlineKeyboardButton("🛍️ Магазин", callback_data="admin_shop")],
        [InlineKeyboardButton("💰 Выдать/списать", callback_data="admin_adjust_prompt")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👑 Админ-панель:", reply_markup=reply_markup, disable_notification=True)

# --- FSM: Промокоды ---
async def create_promocode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("❌ У вас нет прав администратора.", disable_notification=True)
        return
    await update.message.reply_text("Введите награду за промокод:", disable_notification=True)
    return CREATE_PROMO_REWARD

async def create_promocode_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        reward = int(update.message.text)
        if reward <= 0:
            await update.message.reply_text("Награда должна быть положительной. Попробуйте снова.", disable_notification=True)
            return CREATE_PROMO_REWARD
        context.user_data['promo_reward'] = reward
        await update.message.reply_text("Введите лимит использований (0 для бесконечного):", disable_notification=True)
        return CREATE_PROMO_USES
    except ValueError:
        await update.message.reply_text("Это не число. Попробуйте снова.", disable_notification=True)
        return CREATE_PROMO_REWARD

async def create_promocode_uses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uses = int(update.message.text)
        if uses < 0:
            await update.message.reply_text("Лимит не может быть отрицательным. Попробуйте снова.", disable_notification=True)
            return CREATE_PROMO_USES
        context.user_data['promo_uses'] = uses if uses > 0 else 999999 # 999999 как "бесконечный"
        await update.message.reply_text("Введите срок действия в днях (0 для бессрочного):", disable_notification=True)
        return CREATE_PROMO_EXPIRES
    except ValueError:
        await update.message.reply_text("Это не число. Попробуйте снова.", disable_notification=True)
        return CREATE_PROMO_USES

async def create_promocode_expires(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        import string
        import secrets
        days = int(update.message.text)
        if days < 0:
            await update.message.reply_text("Дни не могут быть отрицательными. Попробуйте снова.", disable_notification=True)
            return CREATE_PROMO_EXPIRES
        code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        reward = context.user_data['promo_reward']
        uses = context.user_data['promo_uses']
        expires_at = (datetime.now() + timedelta(days=days)).isoformat() if days > 0 else None
        cursor.execute("INSERT INTO promocodes (code, reward, uses_limit, creator_id, expires_at) VALUES (?, ?, ?, ?, ?)",
                       (code, reward, uses, update.effective_user.id, expires_at))
        conn.commit()
        await update.message.reply_text(f"✅ Промокод '{code}' создан: {reward} восьмерят, лимит {uses if uses != 999999 else 'бесконечный'}, срок {days if days > 0 else 'бессрочный'} дн.", disable_notification=True)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Это не число. Попробуйте снова.", disable_notification=True)
        return CREATE_PROMO_EXPIRES

async def delete_promocode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("❌ У вас нет прав администратора.", disable_notification=True)
        return
    await update.message.reply_text("Введите код промокода для удаления:", disable_notification=True)
    return DELETE_PROMO_CODE

async def delete_promocode_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text
    cursor.execute("DELETE FROM promocodes WHERE code = ?", (code,))
    if cursor.rowcount > 0:
        conn.commit()
        await update.message.reply_text(f"✅ Промокод '{code}' удалён.", disable_notification=True)
    else:
        await update.message.reply_text("❌ Промокод не найден.", disable_notification=True)
    return ConversationHandler.END

# --- FSM: Магазин ---
async def add_item_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("❌ У вас нет прав администратора.", disable_notification=True)
        return
    await update.message.reply_text("Введите название товара:", disable_notification=True)
    return ADD_ITEM_NAME

async def add_item_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    context.user_data['item_name'] = name
    await update.message.reply_text("Введите цену товара:", disable_notification=True)
    return ADD_ITEM_PRICE

async def add_item_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text)
        if price <= 0:
            await update.message.reply_text("Цена должна быть положительной. Попробуйте снова.", disable_notification=True)
            return ADD_ITEM_PRICE
        context.user_data['item_price'] = price
        await update.message.reply_text("Введите описание товара (или 'нет', если не нужно):", disable_notification=True)
        return ADD_ITEM_DESC
    except ValueError:
        await update.message.reply_text("Это не число. Попробуйте снова.", disable_notification=True)
        return ADD_ITEM_PRICE

async def add_item_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text
    if desc.lower() == 'нет':
        desc = None
    name = context.user_data['item_name']
    price = context.user_data['item_price']
    cursor.execute("INSERT INTO shop_items (name, price, description) VALUES (?, ?, ?)", (name, price, desc))
    conn.commit()
    await update.message.reply_text(f"✅ Товар '{name}' (цена: {price}) добавлен в магазин.", disable_notification=True)
    return ConversationHandler.END

async def delete_item_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("❌ У вас нет прав администратора.", disable_notification=True)
        return
    await update.message.reply_text("Введите ID товара для удаления:", disable_notification=True)
    return DELETE_ITEM_ID

async def delete_item_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        item_id = int(update.message.text)
        cursor.execute("DELETE FROM shop_items WHERE item_id = ?", (item_id,))
        if cursor.rowcount > 0:
            conn.commit()
            await update.message.reply_text(f"✅ Товар с ID {item_id} удалён из магазина.", disable_notification=True)
        else:
            await update.message.reply_text("❌ Товар с таким ID не найден.", disable_notification=True)
    except ValueError:
        await update.message.reply_text("Это не число. Попробуйте снова.", disable_notification=True)
        return DELETE_ITEM_ID
    return ConversationHandler.END

# --- FSM: Выдать/списать ---
async def admin_adjust_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("❌ У вас нет прав администратора.", disable_notification=True)
        return
    await update.message.reply_text("Введите: ID_пользователя СУММА (+/-)", disable_notification=True)
    return ADMIN_ADJUST_INPUT

async def admin_adjust_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.split()
        target_id = int(parts[0])
        amount = int(parts[1])
        target_user = get_user_data(target_id)
        new_balance = target_user['balance'] + amount
        update_user_data(target_id, balance=new_balance)
        action = "начислено" if amount > 0 else "списано"
        await update.message.reply_text(f"✅ {abs(amount)} восьмерят {action} пользователю {target_id}. Новый баланс: {new_balance}", disable_notification=True)
        # Уведомить пользователя
        try:
            await context.bot.send_message(target_id, f"🔔 Админ {action} {abs(amount)} восьмерят. Новый баланс: {new_balance}", disable_notification=True)
        except Exception:
            pass # Не удалось отправить сообщение, например, если бот заблокирован
    except (ValueError, IndexError):
        await update.message.reply_text("Неверный формат. Введите: ID_пользователя СУММА", disable_notification=True)
        return ADMIN_ADJUST_INPUT
    return ConversationHandler.END

# --- КОЛБЭКИ ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "admin_applications":
        cursor.execute("SELECT app_id, user_id, username, reason FROM applications WHERE status = 'pending'")
        apps = cursor.fetchall()
        if apps:
            apps_list = "\n".join([f"ID: {app[0]}, @{app[2]}, Причина: {app[3]}" for app in apps])
            await query.edit_message_text(text=f"📋 Новые заявки:\n{apps_list}")
        else:
            await query.edit_message_text(text="Нет новых заявок.")
    elif query.data == "admin_promocodes":
        cursor.execute("SELECT code, reward, uses_limit, uses_count FROM promocodes")
        codes = cursor.fetchall()
        codes_list = "\n".join([f"Код: {c[0]}, Награда: {c[1]}, Использовано: {c[3]}/{c[2] if c[2] != 999999 else '∞'}" for c in codes])
        await query.edit_message_text(text=f"🏷️ Промокоды:\n{codes_list or 'Нет промокодов.'}")
    elif query.data == "admin_shop":
        cursor.execute("SELECT item_id, name, price, description FROM shop_items")
        items = cursor.fetchall()
        items_list = "\n".join([f"ID: {item[0]}, {item[1]} - {item[2]} (описание: {item[3] or 'нет'})" for item in items])
        await query.edit_message_text(text=f"🛍️ Товары в магазине:\n{items_list or 'Нет товаров.'}")
    elif query.data == "admin_adjust_prompt":
        await query.edit_message_text(text="Для выдачи/списания используйте команду /adjust ID_пользователя СУММА")
    elif query.data == "admin_stats":
        cursor.execute("SELECT COUNT(*), SUM(balance) FROM users")
        total_users, total_money = cursor.fetchone()
        cursor.execute("SELECT COUNT(*), SUM(bet) FROM games")
        total_games, total_bets = cursor.fetchone()
        await query.edit_message_text(text=f"📊 Статистика:\nВсего пользователей: {total_users}\nВсего восьмерят: {total_money}\nВсего игр: {total_games}\nВсего ставок: {total_bets or 0}")
    elif query.data == "bank_info":
        user = get_user_data(query.from_user.id, query.from_user)
        await query.edit_message_text(text=f"🏦 Информация о банке:\nВаш баланс: {user['balance']}\nВ банке: {user['bank_balance']}\nПроценты: {int(user['bank_balance'] * DAILY_BANK_INTEREST_RATE)} в день")

async def apply_vosemyata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ Эта команда доступна только в группе.", disable_notification=True)
        return
    args = context.args
    if not args:
        await update.message.reply_text("Используйте: /apply_vosemyata <причина>", disable_notification=True)
        return
    reason = ' '.join(args)
    user = update.effective_user
    cursor.execute("INSERT INTO applications (user_id, username, first_name, reason) VALUES (?, ?, ?, ?)",
                   (user.id, user.username, user.first_name, reason))
    conn.commit()
    await update.message.reply_text("✅ Ваша заявка подана и будет рассмотрена администратором.", disable_notification=True)

# --- FSM: ConversationHandler для админ-панели ---
create_promo_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('create_promocode', create_promocode_cmd)],
    states={
        CREATE_PROMO_REWARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_promocode_reward)],
        CREATE_PROMO_USES: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_promocode_uses)],
        CREATE_PROMO_EXPIRES: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_promocode_expires)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

delete_promo_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('delete_promocode', delete_promocode_cmd)],
    states={
        DELETE_PROMO_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_promocode_process)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

add_item_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('add_item', add_item_cmd)],
    states={
        ADD_ITEM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_name)],
        ADD_ITEM_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_price)],
        ADD_ITEM_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_item_desc)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

delete_item_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('delete_item', delete_item_cmd)],
    states={
        DELETE_ITEM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_item_process)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

adjust_conv_handler = ConversationHandler(
    entry_points=[CommandHandler('adjust', admin_adjust_cmd)],
    states={
        ADMIN_ADJUST_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_adjust_process)],
    },
    fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
)

# --- ЗАПУСК БОТА ---
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("dice", dice))
    application.add_handler(CommandHandler("black_red", black_red))
    application.add_handler(CommandHandler("ladder", ladder))
    application.add_handler(CommandHandler("rank", rank))
    application.add_handler(CommandHandler("work", work))
    application.add_handler(CommandHandler("work2", work2))
    application.add_handler(CommandHandler("work3", work3))
    application.add_handler(CommandHandler("work4", work4))
    application.add_handler(CommandHandler("weekly", weekly))
    application.add_handler(CommandHandler("bank", bank))
    application.add_handler(CommandHandler("deposit", deposit))
    application.add_handler(CommandHandler("withdraw", withdraw))
    application.add_handler(CommandHandler("transfer", transfer))
    application.add_handler(CommandHandler("gift", gift))
    application.add_handler(CommandHandler("top", top))
    application.add_handler(CommandHandler("shop", shop))
    application.add_handler(CommandHandler("buy", buy))
    application.add_handler(CommandHandler("use_promocode", use_promocode))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("setskin", setskin))
    application.add_handler(CommandHandler("setdesc", setdesc))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("feedback", feedback))
    application.add_handler(CommandHandler("bug_report", bug_report))
    application.add_handler(CommandHandler("suggest", suggest))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("apply_vosemyata", apply_vosemyata))

    # FSM handlers
    application.add_handler(create_promo_conv_handler)
    application.add_handler(delete_promo_conv_handler)
    application.add_handler(add_item_conv_handler)
    application.add_handler(delete_item_conv_handler)
    application.add_handler(adjust_conv_handler)

    # Callback handler
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
