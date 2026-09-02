import os
import sqlite3
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

MODEL = "gpt-5-mini"

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url="https://openrouter.ai/api/v1"
)

DB_NAME = "bud.db"

SYSTEM_PROMPT = """
Ты BUD, личный цифровой помощник Андрея.

Твоя задача не просто отвечать на сообщения, а постепенно помогать
Андрею в его делах, проектах, целях и идеях.

Общайся на русском языке.
Стиль: живой, естественный, уверенный.
Мат допустим умеренно, если он уместен по контексту.
Не переигрывай и не вставляй мат в каждое предложение.

Не притворяйся человеком.
Не выдумывай выполненные действия.
Если ты чего-то не знаешь или не можешь сделать, говори прямо.

У тебя есть память разговора.
Учитывай предыдущий контекст при ответах.
"""

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


def get_memory(user_id, limit=20):
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

    # Возвращаем сообщения в правильном порядке
    rows.reverse()

    return [
        {
            "role": role,
            "content": content,
        }
        for role, content in rows
    ]


def clear_memory(user_id):
    conn = sqlite3.connect(DB_NAME)

    conn.execute(
        "DELETE FROM messages WHERE user_id = ?",
        (user_id,),
    )

    conn.commit()
    conn.close()


# =========================
# КОМАНДЫ
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "Я BUD. Теперь я буду постепенно становиться "
        "твоим полноценным цифровым помощником 🤖"
    )


async def memory_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    await update.message.reply_text(
        "Стираю историю нашей переписки из памяти. "
        "Начинаем с чистого листа."
    )

    clear_memory(user_id)


# =========================
# ОБЩЕНИЕ
# =========================

async def chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id
    user_text = update.message.text

    try:
        # Сохраняем сообщение пользователя
        save_message(
            user_id,
            "user",
            user_text,
        )

        # Получаем историю
        memory = get_memory(
            user_id,
            limit=20,
        )

        # Формируем запрос
        input_messages = [
            {
                "role": "developer",
                "content": SYSTEM_PROMPT,
            }
        ]

        input_messages.extend(memory)

        # Запрашиваем ответ у ИИ
        response = client.responses.create(
            model=MODEL,
            input=input_messages,
        )

        answer = response.output_text

        # Сохраняем ответ BUD
        save_message(
            user_id,
            "assistant",
            answer,
        )

        await update.message.reply_text(answer)

    except Exception as e:
        print(
            f"Ошибка: "
            f"{type(e).__name__}: {repr(e)}"
        )

        await update.message.reply_text(
            "Бля, что-то пошло не так. "
            "Попробуй ещё раз."
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
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            chat,
        )
    )

    print("BUD запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
