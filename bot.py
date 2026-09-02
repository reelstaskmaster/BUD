import os
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я твой ИИ-помощник. Пиши мне что угодно."
    )


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    try:
        response = client.responses.create(
            model="gpt-5-mini",
            input=[
                {
                    "role": "developer",
                    "content": (
                        "Ты личный Telegram-помощник AR. "
                        "Общайся по-русски, живо, дружелюбно и естественно. "
                        "Мат допустим умеренно и только если он уместен по контексту. "
                        "Не притворяйся человеком и не говори, что можешь делать то, "
                        "чего на самом деле не можешь."
                    ),
                },
                {
                    "role": "user",
                    "content": user_text,
                },
            ],
        )

        answer = response.output_text
        await update.message.reply_text(answer)

    except Exception as e:
        print(f"Ошибка: {e}")
        await update.message.reply_text(
            "Бля, что-то пошло не так. Попробуй написать ещё раз."
        )


def main():
    telegram_token = os.environ["TELEGRAM_BOT_TOKEN"]

    app = Application.builder().token(telegram_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, chat)
    )

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
