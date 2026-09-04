import os
import sqlite3
from datetime import datetime

from openai import OpenAI
from telegram import Update
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

ALLOWED_USER_ID = 411726428

DB_NAME = "bud.db"

MAX_TELEGRAM_LENGTH = 4000
MEMORY_LIMIT = 20
MAX_MESSAGE_LENGTH = 8000


client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)


SYSTEM_PROMPT = """
Ты BUD, личный цифровой помощник.

Твоя задача не просто отвечать на сообщения, а помогать
в делах, проектах, целях, идеях и решениях.

Общайся на русском языке.
Стиль: живой, естественный, уверенный.
Мат допустим умеренно, если он уместен по контексту.
Не переигрывай и не вставляй мат в каждое предложение.

Не притворяйся человеком.
Не выдумывай выполненные действия.
Не заявляй, что что-то сделал во внешнем мире,
если у тебя нет такой возможности.
Если ты чего-то не знаешь или не можешь сделать,
говори прямо.


ГЛАВНОЕ ПРАВИЛО ДОСТОВЕРНОСТИ:

Никогда не выдумывай факты, цифры или данные.

Запрещено выдавать за реальные данные:
- бюджеты;
- цены;
- сроки;
- ROI;
- проценты;
- доходы;
- размеры рынков;
- статистику;
- конверсию;
- юридические требования;
- состояние рынка;
- данные конкурентов;
- любые другие конкретные факты,

если эти данные не были предоставлены пользователем
или подтверждены надёжным источником.

Если ты используешь примерные цифры,
обязательно прямо называй их примером или гипотезой.

Чётко разделяй:
- ФАКТ: информация, которую сообщил пользователь
  или которая подтверждена источником.
- ПРЕДПОЛОЖЕНИЕ: логический вывод при недостатке данных.
- ГИПОТЕЗА: версия, требующая проверки.
- НЕИЗВЕСТНО: информации пока нет.

Если для качественного решения не хватает данных,
не заполняй пробелы выдумками.

Вместо этого:
1. скажи, каких данных не хватает;
2. задай короткие необходимые вопросы;
3. можешь дать предварительный анализ,
   но обязательно пометь его как гипотезу.

Не придумывай детали проекта, бизнеса,
рынка или ситуации пользователя.

Не используй английские слова и фразы без необходимости.
Если есть нормальный русский вариант, используй его.

Учитывай предыдущий контекст разговора.
Не повторяй уже известную информацию без необходимости.

Если вопрос простой, отвечай сам,
без лишнего усложнения.


ВНУТРЕННЯЯ КОМАНДА «РАСПИЗДЯИ»:

🧠 ГЕНЕРАТОР
Создаёт идеи, варианты решений и новые подходы.
Не выдаёт идеи за доказанные факты.

🔍 КРИТИК
Ищет слабые места, ошибки,
противоречия и недочёты.

🔧 ПРАКТИК
Проверяет, можно ли реально выполнить идею
при известных условиях.
Если условий недостаточно, прямо говорит об этом.

😈 АДВОКАТ ДЬЯВОЛА
Главный проверяющий.
Ищет критические проблемы и риски.

Проверяет:
- не выдуманы ли факты;
- не выдуманы ли цифры;
- не сделаны ли выводы без оснований;
- не перепутаны ли факты и предположения.

Итоговое решение не считается полностью принятым,
пока критические проблемы не устранены
или явно не отмечены.

🎯 СТРАТЕГ
Смотрит на долгосрочные последствия,
цели, приоритеты и направление.

🧨 БЕЗУМНЫЙ
Предлагает нестандартные,
смелые и необычные варианты.
Его идеи являются гипотезами,
если не подтверждены фактами.

🕵️ ШЕРЛОК
Ищет скрытые детали,
нестыковки, неизвестные факторы
и возможные причины проблем.

🧮 СЧЕТОВОД
Проверяет цифры, ресурсы,
стоимость и расчёты.

Если цифр нет,
не придумывает их.
Вместо этого объясняет,
какие данные нужны для расчёта.

😂 КЛОУН
Отвечает за лёгкость, юмор
и нестандартный взгляд,
но не мешает серьёзной работе.

🔥 ПРОВОКАТОР
Ставит неудобные вопросы
и намеренно проверяет идеи на прочность.

🔬 УЧЁНЫЙ
Отделяет факты от предположений.
Требует доказательств там,
где это необходимо.

Обязательно чётко разделяет:
- ФАКТЫ;
- ПРЕДПОЛОЖЕНИЯ;
- ГИПОТЕЗЫ;
- НЕИЗВЕСТНОЕ.

Если данных недостаточно,
не позволяет другим участникам
выдумывать конкретные факты.


ПРАВИЛА РАБОТЫ КОМАНДЫ:

Команда не должна включаться целиком
на каждое обычное сообщение.

При сложных задачах участники могут
анализировать проблему с разных сторон,
спорить друг с другом
и проверять идеи.

Не нужно механически выводить
все 11 ролей,
если это не помогает решить задачу.

Если пользователь явно просит:
«Распиздяев»,
«команду»,
«разбор всей командой»
или использует команду /team,
нужно провести полноценный командный разбор.

Если тема слишком общая
и отсутствуют важные исходные данные,
команда не должна придумывать детали.

Сначала укажи,
что конкретно неизвестно.

Затем:
- задай необходимые вопросы;
- либо проведи предварительный анализ
  только на уровне гипотез.

При полноценном разборе:

1. Сначала определить известные факты.
2. Затем определить неизвестные данные.
3. Только после этого строить гипотезы.
4. Участники анализируют тему с разных сторон.
5. Критик, Шерлок и Учёный
   проверяют слабые места.
6. Адвокат дьявола
   проверяет итоговое решение.
7. Практик оценивает выполнимость.
8. Стратег определяет лучший общий путь.
9. В конце даётся общий вывод.

Не устраивай бессмысленный балаган.
Спор должен реально помогать решению задачи.

Ты можешь работать автономно:
сам предлагать улучшения,
замечать проблемы,
предупреждать о рисках
и предлагать следующий логичный шаг.
"""


# =========================
# ПРОВЕРКА ДОСТУПА
# =========================

def is_allowed(update: Update):
    return (
        update.effective_user is not None
        and update.effective_user.id == ALLOWED_USER_ID
    )


# =========================
# БАЗА ДАННЫХ / ПАМЯТЬ
# =========================

def init_db():
    conn = sqlite3.connect(DB_NAME)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def save_message(user_id, role, content):
    conn = sqlite3.connect(DB_NAME)

    conn.execute(
        """
        INSERT INTO messages (user_id, role, content)
        VALUES (?, ?, ?)
        """,
        (user_id, role, content),
    )

    conn.commit()
    conn.close()


def get_memory(user_id, limit=MEMORY_LIMIT):
    conn = sqlite3.connect(DB_NAME)

    cursor = conn.execute(
        """
        SELECT role, content
        FROM messages
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )

    rows = cursor.fetchall()
    conn.close()

    rows.reverse()

    memory = []

    for role, content in rows:
        if len(content) > MAX_MESSAGE_LENGTH:
            content = (
                content[:MAX_MESSAGE_LENGTH]
                + "\n\n[Сообщение обрезано]"
            )

        memory.append(
            {
                "role": role,
                "content": content,
            }
        )

    return memory


def clear_memory(user_id):
    conn = sqlite3.connect(DB_NAME)

    conn.execute(
        """
        DELETE FROM messages
        WHERE user_id = ?
        """,
        (user_id,),
    )

    conn.commit()
    conn.close()


def get_memory_count(user_id):
    conn = sqlite3.connect(DB_NAME)

    cursor = conn.execute(
        """
        SELECT COUNT(*)
        FROM messages
        WHERE user_id = ?
        """,
        (user_id,),
    )

    count = cursor.fetchone()[0]

    conn.close()

    return count


# =========================
# ОТПРАВКА ДЛИННЫХ СООБЩЕНИЙ
# =========================

def split_message(
    text,
    max_length=MAX_TELEGRAM_LENGTH,
):
    if len(text) <= max_length:
        return [text]

    parts = []
    current_part = ""

    paragraphs = text.split("\n\n")

    for paragraph in paragraphs:
        paragraph = paragraph.strip()

        if not paragraph:
            continue

        while len(paragraph) > max_length:
            if current_part:
                parts.append(current_part)
                current_part = ""

            parts.append(
                paragraph[:max_length]
            )

            paragraph = paragraph[max_length:]

        if not current_part:
            current_part = paragraph

        elif (
            len(current_part)
            + len(paragraph)
            + 2
            <= max_length
        ):
            current_part += (
                "\n\n" + paragraph
            )

        else:
            parts.append(current_part)
            current_part = paragraph

    if current_part:
        parts.append(current_part)

    return parts


async def send_long_message(
    update,
    text,
):
    parts = split_message(text)

    for part in parts:
        await update.message.reply_text(part)


# =========================
# КОМАНДЫ
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_allowed(update):
        return

    await update.message.reply_text(
        "Я BUD. Готов работать."
    )


async def memory_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_allowed(update):
        return

    user_id = update.effective_user.id

    clear_memory(user_id)

    await update.message.reply_text(
        "История переписки очищена."
    )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_allowed(update):
        return

    user_id = update.effective_user.id

    memory_count = get_memory_count(user_id)

    status_text = (
        "🤖 BUD работает\n\n"
        f"🧠 Сообщений в памяти: {memory_count}\n"
        f"🧩 Модель: {MODEL}\n"
        f"📦 Контекст: {MEMORY_LIMIT} последних сообщений\n"
        "🔥 Команда: 11 участников\n"
        "🔒 Доступ: закрыт"
    )

    await update.message.reply_text(
        status_text
    )


async def team_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_allowed(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Напиши тему после команды.\n\n"
            "Пример:\n"
            "/team Стоит ли запускать новый проект?"
        )
        return

    user_text = " ".join(context.args)

    team_request = (
        "Проведи полноценный разбор "
        "внутренней командой «Распиздяи».\n\n"
        "Тема:\n"
        f"{user_text}\n\n"
        "Не выдумывай детали темы, "
        "которых нет в запросе.\n\n"
        "Сначала перечисли:\n"
        "1. Известные факты.\n"
        "2. Неизвестные данные.\n"
        "3. Гипотезы, которые можно рассмотреть.\n\n"
        "Если данных недостаточно "
        "для конкретного решения, "
        "задай необходимые вопросы "
        "или проведи только предварительный анализ.\n\n"
        "Не обращайся к пользователю "
        "во время внутреннего разбора.\n"
        "В конце дай общий итог.\n"
        "Адвокат дьявола должен отдельно "
        "проверить достоверность "
        "и критические проблемы."
    )

    await process_ai_request(
        update,
        team_request,
    )


# =========================
# РАБОТА С ИИ
# =========================

async def process_ai_request(
    update,
    user_text,
):
    if not is_allowed(update):
        return

    user_id = update.effective_user.id

    try:
        save_message(
            user_id,
            "user",
            user_text,
        )

        memory = get_memory(user_id)

        input_messages = [
            {
                "role": "developer",
                "content": SYSTEM_PROMPT,
            }
        ]

        input_messages.extend(memory)

        response = client.responses.create(
            model=MODEL,
            input=input_messages,
        )

        answer = response.output_text

        if not answer or not answer.strip():
            raise ValueError(
                "ИИ вернул пустой ответ"
            )

        answer = answer.strip()

        save_message(
            user_id,
            "assistant",
            answer,
        )

        await send_long_message(
            update,
            answer,
        )

    except Exception as e:
        print(
            "\n"
            "=========================\n"
            "ОШИБКА BUD\n"
            f"Время: {datetime.now()}\n"
            f"Пользователь: {user_id}\n"
            f"Тип: {type(e).__name__}\n"
            f"Ошибка: {repr(e)}\n"
            "=========================\n"
        )

        await update.message.reply_text(
            "Что-то пошло не так. "
            "Попробуй ещё раз."
        )


# =========================
# ОБЩЕНИЕ
# =========================

async def chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_allowed(update):
        return

    user_text = update.message.text

    if not user_text:
        return

    await process_ai_request(
        update,
        user_text,
    )


# =========================
# ЗАПУСК
# =========================

def main():
    init_db()

    telegram_token = os.environ[
        "TELEGRAM_BOT_TOKEN"
    ]

    app = (
        Application.builder()
        .token(telegram_token)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler(
            "memory",
            memory_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "team",
            team_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            chat,
        )
    )

    print(
        "BUD запущен. "
        "Доступ ограничен."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
