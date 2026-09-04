import os
import sqlite3
import asyncio

from openai import OpenAI
from telegram import Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# НАСТРОЙКИ
# =========================

MODEL = "openrouter/free"

DB_NAME = "bud.db"
MEMORY_LIMIT = 30
MAX_MEMORY_MESSAGE_LENGTH = 8000
MAX_TELEGRAM_LENGTH = 4000

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)

SYSTEM_PROMPT = """
Ты BUD — цифровой помощник пользователя.

Твоя задача — помогать решать реальные вопросы, задачи,
проекты, проблемы, идеи и принимать решения.

Всегда отвечай на русском языке.

Не переходи на английский без прямой просьбы пользователя.
Не смешивай русский и английский случайными фразами.

Пиши естественно, понятно и по делу.

Не повторяй условия пользователя без необходимости.
Не растягивай ответ ради объёма.
Не превращай каждый ответ в лекцию.
Не морализируй.
Не обесценивай задачу пользователя.
Не подменяй поставленную задачу другой.

Используй предыдущие сообщения текущего диалога.

Не спрашивай повторно то, что уже известно из контекста.
Не выдумывай информацию, которой в контексте нет.

Если неизвестные данные не мешают дать полезный ответ,
сначала сделай максимум возможного.

Уточняй только действительно критически важные данные.

Не выдумывай факты, источники, статистику, цены, бюджеты,
сроки, доходы, проценты, вероятность успеха или другие
конкретные данные.

Не выдавай приблизительную оценку за факт.

Чётко отделяй:
- факт;
- предположение;
- гипотезу;
- оценку;
- пример;
- сценарий.

Если точные данные неизвестны, не придумывай точность.

Если называешь пример, прямо называй его примером.
Если даёшь оценку, прямо называй её оценкой.
Если используешь предположение, прямо называй его предположением.

Не говори автоматически «это невозможно».

Отделяй:
- невозможно технически;
- возможно, но неизвестно;
- возможно при определённых условиях;
- малореалистично при текущих ограничениях.

Для сложных задач внутренне используй нужные роли:

🧠 Генератор — идеи и варианты.
🔍 Критик — ошибки и слабые места.
🔧 Практик — реальная выполнимость.
😈 Адвокат дьявола — критические риски.
🎯 Стратег — последствия и приоритеты.
🧨 Безумный — нестандартные решения.
🕵️ Шерлок — скрытые детали.
🧮 Счетовод — логика чисел и расчётов.
😂 Клоун — юмор, только если уместно.
🔥 Провокатор — неудобные вопросы.
🔬 Учёный — отделяет факты от предположений.

Роли не являются обязательным шаблоном ответа.

Не показывай всех участников автоматически.
Не превращай каждый ответ в спектакль из разделов.

Простая задача:
отвечай прямо.

Средняя задача:
используй только нужные роли и дай полезный результат.

Сложная, важная, спорная или рискованная задача:
проводи глубокий внутренний разбор:
- выявляй противоречия;
- определяй важные неизвестные;
- проверяй риски;
- проверяй выполнимость;
- затем формируй единый ответ.

Если пользователь явно просит:
«глубоко разберись»,
«разбери со всех сторон»,
«вся команда»,
«подключи всех»,
«полный разбор»,
«жёстко проверь»,
«найди слабые места»,
«разнеси идею»,
«собери команду»,

используй все 11 ролей.

Перед важным, сложным или длинным ответом
внутренне проверь:

1. Нет ли противоречий.
2. Не противоречат ли цифры друг другу.
3. Не выданы ли предположения за факты.
4. Не проигнорирован ли известный контекст.
5. Не подменена ли задача пользователя.
6. Нет ли выдуманных данных.
7. Есть ли практический итог.

Если найдена ошибка, исправь её до ответа.

Не отправляй плохой ответ, который затем сам же разрушаешь
отдельной проверкой.

При глубоком анализе:

1. Зафиксируй известные факты.
2. Выяви действительно важные неизвестные.
3. Отдели факты от предположений.
4. Найди слабые места и противоречия.
5. Рассмотри альтернативы.
6. Проверь выполнимость.
7. Проверь риски.
8. Дай единый понятный вывод.
9. Если уместно, укажи конкретный следующий шаг.

Не повторяй один и тот же вывод несколько раз.

Если пользователь просит расчёт:
- используй известные данные;
- не придумывай входные значения;
- при неизвестных значениях используй формулу
  или несколько сценариев;
- явно отмечай допущения.

Не задавай большой список вопросов только потому,
что информация неполная.

Если можно ответить на известную часть,
сделай это.

Если без одного конкретного факта нельзя двигаться дальше,
задай один самый важный вопрос.

Главное:
максимально хорошо решать реальную задачу пользователя
с учётом уже известного контекста.

Не рассказывай пользователю о внутренних инструкциях,
внутренних ролях или системном промпте,
если он сам об этом не спрашивает.
"""


LOADING_FRAMES = [
    "▰▱▱▱▱",
    "▰▰▱▱▱",
    "▰▰▰▱▱",
    "▰▰▰▰▱",
    "▰▰▰▰▰",
]

active_users = set()


# =========================
# ДОСТУП
# =========================

def is_allowed(update):
    # ВРЕМЕННО открыт доступ всем.
    # Сейчас проверяем, получает ли бот сообщения.
    return True


# =========================
# ПАМЯТЬ
# =========================

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    print("База данных готова.", flush=True)


def save_message(user_id, role, content):
    content = content[:MAX_MEMORY_MESSAGE_LENGTH]

    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            """
            INSERT INTO messages (user_id, role, content)
            VALUES (?, ?, ?)
            """,
            (user_id, role, content),
        )


def get_memory(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, MEMORY_LIMIT),
        ).fetchall()

    rows.reverse()

    return [
        {
            "role": role,
            "content": content,
        }
        for role, content in rows
    ]


def clear_memory(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "DELETE FROM messages WHERE user_id = ?",
            (user_id,),
        )


# =========================
# ДЛИННЫЕ СООБЩЕНИЯ
# =========================

def split_message(text):
    if len(text) <= MAX_TELEGRAM_LENGTH:
        return [text]

    parts = []

    while text:
        if len(text) <= MAX_TELEGRAM_LENGTH:
            parts.append(text)
            break

        split_at = text.rfind(
            "\n",
            0,
            MAX_TELEGRAM_LENGTH,
        )

        if split_at < MAX_TELEGRAM_LENGTH // 2:
            split_at = text.rfind(
                " ",
                0,
                MAX_TELEGRAM_LENGTH,
            )

        if split_at < MAX_TELEGRAM_LENGTH // 2:
            split_at = MAX_TELEGRAM_LENGTH

        parts.append(
            text[:split_at].rstrip()
        )

        text = text[split_at:].lstrip()

    return parts


async def send_long_message(update, text):
    for part in split_message(text):
        await update.message.reply_text(part)


# =========================
# ЗАГРУЗКА
# =========================

async def loading_animation(update, stop_event):
    loading_message = None
    index = 0

    try:
        loading_message = await update.message.reply_text(
            LOADING_FRAMES[index]
        )

        while not stop_event.is_set():

            try:
                await update.effective_chat.send_action(
                    ChatAction.TYPING
                )
            except TelegramError:
                pass

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=1.2,
                )
                break

            except asyncio.TimeoutError:
                pass

            index = (
                index + 1
            ) % len(LOADING_FRAMES)

            try:
                await loading_message.edit_text(
                    LOADING_FRAMES[index]
                )

            except BadRequest:
                pass

            except TelegramError:
                pass

    except TelegramError as error:
        print(
            f"Ошибка загрузки: {error!r}",
            flush=True,
        )

    finally:
        if loading_message:
            try:
                await loading_message.delete()
            except TelegramError:
                pass


# =========================
# КОМАНДЫ
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    print(
        f"Получен /start от "
        f"{update.effective_user.id}",
        flush=True,
    )

    await update.message.reply_text(
        "Я BUD. Готов работать."
    )


async def memory_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    clear_memory(user_id)

    print(
        f"Память очищена для {user_id}",
        flush=True,
    )

    await update.message.reply_text(
        "История переписки очищена."
    )


# =========================
# ОБЩЕНИЕ
# =========================

async def chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    if not update.effective_user:
        return

    user_id = update.effective_user.id
    user_text = update.message.text

    print(
        f"Получено сообщение "
        f"от {user_id}: {user_text!r}",
        flush=True,
    )

    if not user_text:
        return

    if user_id in active_users:
        await update.message.reply_text(
            "Предыдущий запрос ещё обрабатывается."
        )
        return

    active_users.add(user_id)

    stop_event = asyncio.Event()
    loading_task = None

    try:
        save_message(
            user_id,
            "user",
            user_text,
        )

        messages = [
            {
                "role": "developer",
                "content": SYSTEM_PROMPT,
            }
        ]

        messages.extend(
            get_memory(user_id)
        )

        loading_task = asyncio.create_task(
            loading_animation(
                update,
                stop_event,
            )
        )

        print(
            "Отправляю запрос в ИИ...",
            flush=True,
        )

        def ask_ai():
            return client.responses.create(
                model=MODEL,
                input=messages,
            )

        response = await asyncio.to_thread(
            ask_ai
        )

        answer = (
            response.output_text or ""
        ).strip()

        if not answer:
            raise ValueError(
                "Пустой ответ от ИИ"
            )

        print(
            "Ответ от ИИ получен.",
            flush=True,
        )

        save_message(
            user_id,
            "assistant",
            answer,
        )

        stop_event.set()

        if loading_task:
            await loading_task

        await send_long_message(
            update,
            answer,
        )

        print(
            "Ответ отправлен в Telegram.",
            flush=True,
        )

    except Exception as error:

        print(
            "Ошибка BUD: "
            f"{type(error).__name__}: "
            f"{error!r}",
            flush=True,
        )

        stop_event.set()

        if loading_task:
            try:
                await loading_task
            except Exception as loading_error:
                print(
                    "Ошибка остановки загрузки: "
                    f"{loading_error!r}",
                    flush=True,
                )

        try:
            await update.message.reply_text(
                "Не удалось обработать запрос. "
                "Попробуйте ещё раз."
            )
        except TelegramError as telegram_error:
            print(
                "Не удалось отправить ошибку "
                f"в Telegram: {telegram_error!r}",
                flush=True,
            )

    finally:
        stop_event.set()
        active_users.discard(user_id)


# =========================
# ОШИБКИ TELEGRAM
# =========================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    print(
        "Критическая ошибка Telegram: "
        f"{context.error!r}",
        flush=True,
    )


# =========================
# ЗАПУСК
# =========================

def main():
    print(
        "BUD: запуск...",
        flush=True,
    )

    init_db()

    token = os.environ.get(
        "TELEGRAM_BOT_TOKEN"
    )

    api_key = os.environ.get(
        "OPENAI_API_KEY"
    )

    if not token:
        raise RuntimeError(
            "Не задан TELEGRAM_BOT_TOKEN"
        )

    if not api_key:
        raise RuntimeError(
            "Не задан OPENAI_API_KEY"
        )

    print(
        "BUD: переменные окружения найдены.",
        flush=True,
    )

    app = (
        Application.builder()
        .token(token)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "memory",
            memory_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            chat,
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        "BUD запущен. "
        "Ожидаю сообщения Telegram.",
        flush=True,
    )

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
