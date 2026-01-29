#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram AI Auto-Responder для личного аккаунта
Автоответчик с ИИ через Telethon + Vision для анализа изображений
"""

import asyncio
import json
import os
import sys
import logging
from datetime import datetime
import aiohttp
import urllib3
import signal
import base64

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from telethon import TelegramClient, events
    from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
    import speech_recognition as sr
    from pydub import AudioSegment
except ImportError:
    print("📦 Установка необходимых библиотек...")
    os.system("pip install telethon speechrecognition pydub aiohttp --break-system-packages")
    print("✅ Библиотеки установлены! Перезапустите скрипт.")
    sys.exit(1)

# =============== КОНФИГУРАЦИЯ ===============
API_ID = "35452135"  # Получить на https://my.telegram.org
API_HASH = "222ef405491ecfb6be7d642af9a741d8"
PHONE = "+7962302276736548"  # Формат: +79991234567

# AI API настройки
AI_API_URL = "http://api.onlysq.ru/ai/v2"
AI_MODEL = "gemini-3-flash"  # Поддерживает vision

# Файлы
DB_FILE = "telegram_history.json"
SESSION_NAME = "telegram_ai_session"

# Режимы работы
ENABLED = True  # Автоответы включены
IGNORE_GROUPS = True  # Игнорировать группы
IGNORE_CHANNELS = True  # Игнорировать каналы
DELAY_BEFORE_REPLY = 2  # Задержка перед ответом (секунды)

# =============== НАСТРОЙКА ЛОГИРОВАНИЯ ===============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('telegram_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# =============== БАЗА ДАННЫХ JSON ===============
class Database:
    def __init__(self, filename):
        self.filename = filename
        self.data = self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Ошибка загрузки БД: {e}")
                return {"conversations": {}}
        return {"conversations": {}}

    def save(self):
        try:
            with open(self.filename, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения БД: {e}")

    def add_message(self, chat_id, role, content):
        chat_id = str(chat_id)
        if chat_id not in self.data["conversations"]:
            self.data["conversations"][chat_id] = []

        self.data["conversations"][chat_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

        # Оставляем последние 20 сообщений
        if len(self.data["conversations"][chat_id]) > 20:
            self.data["conversations"][chat_id] = self.data["conversations"][chat_id][-20:]

        self.save()

    def get_history(self, chat_id, limit=10):
        chat_id = str(chat_id)
        if chat_id not in self.data["conversations"]:
            return []

        messages = self.data["conversations"][chat_id][-limit:]
        # Возвращаем только role и content для API
        return [{"role": msg["role"], "content": msg["content"]} for msg in messages]

    def clear_history(self, chat_id):
        chat_id = str(chat_id)
        if chat_id in self.data["conversations"]:
            self.data["conversations"][chat_id] = []
            self.save()


# =============== AI ОБРАБОТЧИК ===============
class AIHandler:
    def __init__(self, api_url, model):
        self.api_url = api_url
        self.model = model

    async def get_response(self, messages):
        """Отправить запрос к AI API"""
        headers = {
            "Authorization": "Bearer openai",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "request": {
                "messages": messages
            }
        }

        try:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                        self.api_url,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content']
                    else:
                        error_text = await response.text()
                        logger.error(f"API ошибка {response.status}: {error_text}")
                        return None
        except asyncio.TimeoutError:
            logger.error("Таймаут при запросе к API")
            return None
        except Exception as e:
            logger.error(f"Ошибка AI запроса: {e}")
            return None

    async def analyze_image(self, image_path, user_caption=""):
        """Анализировать изображение с помощью Vision API"""
        try:
            # Читаем изображение и конвертируем в base64
            with open(image_path, 'rb') as image_file:
                image_data = base64.b64encode(image_file.read()).decode('utf-8')

            # Формируем запрос с изображением
            prompt = user_caption if user_caption else "опиши что на фото"

            messages = [
                {
                    "role": "system",
                    "content": "ты обычный человек, описывай изображения естественно и коротко, пиши с маленькой буквы, используй сленг когда уместно."
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}"
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]

            response = await self.get_response(messages)

            if response:
                # Форматируем ответ как обычно
                response = response.replace('**', '').replace('*', '').replace('`', '')
                if response and len(response) > 0 and response[0].isupper() and not response[0:2].isupper():
                    response = response[0].lower() + response[1:]

            return response

        except Exception as e:
            logger.error(f"Ошибка анализа изображения: {e}")
            return None

    async def process_message(self, user_message, history):
        """Обработать сообщение с учетом истории"""
        # Формируем список сообщений для API
        messages = []

        # Системный промпт
        messages.append({
            "role": "system",
            "content": "ты обычный человек, общайся естественно, пиши с маленькой буквы, используй сленг и эмодзи когда уместно. не используй форматирование markdown. отвечай коротко и по делу как в переписке."
        })

        # Добавляем историю
        messages.extend(history)

        # Добавляем текущее сообщение
        messages.append({
            "role": "user",
            "content": user_message
        })

        # Получаем ответ
        response = await self.get_response(messages)

        if response:
            # Убираем markdown форматирование
            response = response.replace('**', '').replace('*', '').replace('`', '')
            # Делаем первую букву маленькой если нужно
            if response and len(response) > 0 and response[0].isupper() and not response[0:2].isupper():
                response = response[0].lower() + response[1:]

        return response


# =============== ОБРАБОТКА МЕДИА ===============
class MediaHandler:
    @staticmethod
    async def transcribe_voice(file_path):
        """Распознать голосовое сообщение"""
        try:
            # Конвертируем в WAV
            audio = AudioSegment.from_file(file_path)
            wav_path = file_path.replace('.ogg', '.wav')
            audio.export(wav_path, format='wav')

            # Распознаем речь через Google
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data, language='ru-RU')

            # Удаляем временные файлы
            try:
                os.remove(wav_path)
            except:
                pass

            return text
        except sr.UnknownValueError:
            logger.error("Не удалось распознать речь")
            return None
        except sr.RequestError as e:
            logger.error(f"Ошибка Google Speech API: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка распознавания: {e}")
            return None


# =============== TELEGRAM BOT ===============
class TelegramBot:
    def __init__(self):
        self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        self.db = Database(DB_FILE)
        self.ai = AIHandler(AI_API_URL, AI_MODEL)
        self.media = MediaHandler()
        self.me = None
        self.running = True

    async def start(self):
        """Запустить бота"""
        await self.client.start(phone=PHONE)
        self.me = await self.client.get_me()
        logger.info(f"✅ Бот запущен для: {self.me.first_name} (@{self.me.username})")
        logger.info(f"📱 ID: {self.me.id}")
        logger.info(f"⚙️ Автоответы: {'Включены' if ENABLED else 'Выключены'}")
        logger.info(f"👥 Группы: {'Игнорируются' if IGNORE_GROUPS else 'Обрабатываются'}")
        logger.info(f"🖼️ Vision: Включено (бот может видеть изображения)")

        # Регистрируем обработчик входящих сообщений
        @self.client.on(events.NewMessage(incoming=True))
        async def handle_message(event):
            if self.running:
                await self.process_message(event)

        # Обработка сигналов для корректного завершения
        def signal_handler(signum, frame):
            logger.info("🛑 Получен сигнал остановки...")
            self.running = False
            self.client.disconnect()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Запускаем клиент
        await self.client.run_until_disconnected()

    async def process_message(self, event):
        """Обработать входящее сообщение"""
        try:
            # Проверки
            if not ENABLED:
                return

            # Игнорируем свои сообщения
            if event.sender_id == self.me.id:
                return

            # Игнорируем группы
            if event.is_group and IGNORE_GROUPS:
                return

            # Игнорируем каналы
            if event.is_channel and IGNORE_CHANNELS:
                return

            chat_id = event.chat_id

            # Получаем информацию об отправителе
            try:
                sender = await event.get_sender()
                sender_name = sender.first_name if hasattr(sender,
                                                           'first_name') and sender.first_name else "Пользователь"
            except:
                sender_name = "Пользователь"

            logger.info(f"📨 Сообщение от {sender_name} (ID: {chat_id})")

            # Обрабатываем разные типы сообщений
            message_text = ""
            photo_caption = ""

            # 1. Текстовое сообщение
            if event.text and not event.photo:
                message_text = event.text
                logger.info(f"💬 Текст: {message_text[:50]}...")

            # 2. Голосовое сообщение
            elif event.voice:
                logger.info("🎤 Получено голосовое сообщение")

                # Показываем что слушаем
                try:
                    await event.reply("слушаю...")
                except:
                    pass

                # Скачиваем и распознаем
                try:
                    file_path = await event.download_media(file='voice_temp.ogg')
                    transcribed = await self.media.transcribe_voice(file_path)

                    # Удаляем файл
                    try:
                        os.remove(file_path)
                    except:
                        pass

                    if transcribed:
                        message_text = f"[голосовое сообщение]: {transcribed}"
                        logger.info(f"✅ Распознано: {transcribed}")
                    else:
                        await event.reply("не смог разобрать, повтори текстом")
                        return
                except Exception as e:
                    logger.error(f"Ошибка обработки голосового: {e}")
                    return

            # 3. Фото (ОБНОВЛЕННАЯ ОБРАБОТКА)
            elif event.photo:
                logger.info("📷 Получено фото - анализирую...")

                # Показываем что смотрим
                try:
                    await event.reply("смотрю...")
                except:
                    pass

                try:
                    # Скачиваем фото
                    photo_path = await event.download_media(file='photo_temp.jpg')

                    # Получаем подпись к фото если есть
                    photo_caption = event.message.message if event.message.message else ""

                    # Анализируем изображение через AI
                    image_description = await self.ai.analyze_image(photo_path, photo_caption)

                    # Удаляем файл
                    try:
                        os.remove(photo_path)
                    except:
                        pass

                    if image_description:
                        # Если был текст с фото, добавляем его в контекст
                        if photo_caption:
                            message_text = f"[фото с текстом '{photo_caption}']: {image_description}"
                        else:
                            message_text = f"[фото]: {image_description}"

                        logger.info(f"✅ Анализ фото: {image_description[:50]}...")
                    else:
                        await event.reply("хм, не могу разобрать что на фото")
                        return

                except Exception as e:
                    logger.error(f"Ошибка анализа фото: {e}")
                    await event.reply("что-то с фото, попробуй еще раз")
                    return

            # 4. Документ/Файл (может быть аудио)
            elif event.document:
                mime_type = event.document.mime_type if event.document.mime_type else ""

                if 'audio' in mime_type or 'ogg' in mime_type:
                    logger.info("🎵 Получено аудио сообщение")

                    try:
                        await event.reply("слушаю...")
                    except:
                        pass

                    try:
                        file_path = await event.download_media(file='audio_temp')
                        transcribed = await self.media.transcribe_voice(file_path)

                        try:
                            os.remove(file_path)
                        except:
                            pass

                        if transcribed:
                            message_text = f"[аудио сообщение]: {transcribed}"
                            logger.info(f"✅ Распознано: {transcribed}")
                        else:
                            await event.reply("не смог распознать аудио")
                            return
                    except Exception as e:
                        logger.error(f"Ошибка обработки аудио: {e}")
                        return
                else:
                    logger.info("📎 Получен файл")
                    message_text = "[пользователь отправил файл]"
                    if event.message.message:
                        message_text += f": {event.message.message}"

            # Если сообщение пустое - игнорируем
            if not message_text:
                return

            # Сохраняем в историю
            self.db.add_message(chat_id, "user", message_text)

            # Получаем историю диалога
            history = self.db.get_history(chat_id, limit=10)

            # Показываем "печатает..."
            async with self.client.action(chat_id, 'typing'):
                # Генерируем ответ от ИИ
                logger.info("🤖 Генерирую ответ...")
                response = await self.ai.process_message(message_text, history)

                # Имитация печати (естественная пауза)
                if DELAY_BEFORE_REPLY > 0:
                    await asyncio.sleep(DELAY_BEFORE_REPLY)

            if response:
                # Отправляем ответ
                try:
                    await event.reply(response)
                    logger.info(f"✅ Отправлен ответ: {response[:50]}...")

                    # Сохраняем ответ в историю
                    self.db.add_message(chat_id, "assistant", response)
                except Exception as e:
                    logger.error(f"Ошибка отправки ответа: {e}")
            else:
                logger.error("❌ Не удалось получить ответ от AI")

        except Exception as e:
            logger.error(f"❌ Ошибка обработки сообщения: {e}", exc_info=True)


# =============== ГЛАВНАЯ ФУНКЦИЯ ===============
def main():
    print("""
╔═══════════════════════════════════════════╗
║   Telegram AI Auto-Responder v2.1         ║
║   Автоответчик + Vision (анализ фото)     ║
╚═══════════════════════════════════════════╝
    """)

    # Проверка конфигурации
    if API_ID == "YOUR_API_ID" or API_HASH == "YOUR_API_HASH":
        print("""
⚠️  НЕОБХОДИМА НАСТРОЙКА!

1. Получите API_ID и API_HASH:
   👉 https://my.telegram.org

2. Откройте файл telegram_ai_bot.py

3. Замените строки:
   API_ID = "YOUR_API_ID"      →  API_ID = "12345678"
   API_HASH = "YOUR_API_HASH"   →  API_HASH = "abc..."
   PHONE = "YOUR_PHONE"         →  PHONE = "+79991234567"

4. Сохраните файл и перезапустите
        """)
        sys.exit(1)

    # Проверка FFmpeg для голосовых
    try:
        import subprocess
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True)
        if result.returncode != 0:
            raise FileNotFoundError
    except:
        print("""
⚠️  FFmpeg не установлен!

Для распознавания голосовых сообщений установите FFmpeg:

  Ubuntu/Debian:  sudo apt install ffmpeg
  macOS:          brew install ffmpeg
  Windows:        скачайте с ffmpeg.org

Бот запустится, но голосовые работать не будут.
        """)

    print("🚀 Запуск бота...\n")

    bot = TelegramBot()

    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        print("\n\n✅ Бот остановлен (Ctrl+C)")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
        print(f"\n❌ Ошибка: {e}")


if __name__ == "__main__":
    main()
