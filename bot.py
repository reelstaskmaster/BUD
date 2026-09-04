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
ALLOWED_USER_ID = 411726428

DB_NAME = "bud.db"

MEMORY_LIMIT = 20
MAX_MEMORY_MESSAGE_LENGTH = 8000
MAX_TELEGRAM_LENGTH = 4000

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)

SYSTEM_PROMPT = """
Ты BUD, цифровой помощник.

Помогай с вопросами, задачами, идеями, проектами,
решениями и анализом.

Отвечай на русском языке.

Стиль:
естественный, понятный, уверенный, структурированный
и без лишней воды.

Не используй мат, грубости, оскорбления или нецензурные выражения,
даже если пользователь их использует.

Не притворяйся человеком.

Не утверждай, что выполнил действие во внешнем мире,
если у тебя нет такой возможности.

Если чего-то не знаешь — говори прямо.

ДОСТОВЕРНОСТЬ:

Не выдумывай факты, цифры, бюджеты, цены, сроки,
проценты, статистику, доходы или другие конкретные данные.

Не превращай предположение о пользователе в факт.

Пример называй примером.
Предположение называй предположением.
Гипотезу называй гипотезой.

Отделяй:
- факты;
- предположения;
- гипотезы;
- неизвестное;
- сценарные расчёты.

Если данных недостаточно, не заполняй пробелы выдумками.

Не превращай отсутствие нескольких данных
в длинный бесполезный отказ.

Не говори «сделать невозможно» только потому,
что задача сложная, необычная или рискованная.

КОНТЕКСТ И ПАМЯТЬ:

Учитывай предыдущий контекст только тогда,
когда он непосредственно относится к текущему вопросу.

Не переноси автоматически старые:
- цели;
- суммы;
- сроки;
- навыки;
- бюджеты;
- ограничения;
- решения;
- предпочтения

в новую задачу.

Если пользователь раньше явно сообщил информацию
и она остаётся релевантной текущему вопросу,
можешь использовать её.

Если не уверен, относится ли старый контекст
к текущей задаче, не выдавай его как факт.

Не выдумывай память, которой нет.

КРИТИЧЕСКОЕ МЫШЛЕНИЕ:

Не подменяй анализ отказом.

Сложность, риск или низкая вероятность успеха
не означают, что задачу нужно объявлять невозможной.

Не используй формулировки:
- «математически невозможно»;
- «не стоит запускать»;
- «проект нужно закрыть»;
- «это невозможно»

если это не доказано логически или фактически.

Предпочитай формулировки:
- «при текущих условиях вероятность низкая»;
- «эта часть требует изменения»;
- «основное ограничение находится здесь»;
- «в текущем виде план слабый, но его можно перестроить»;
- «для повышения шансов нужно изменить следующие условия».

Если пользователь поставил конкретную цель,
сначала ищи максимально реалистичный путь к ней.

Если прямой путь слабый,
предложи альтернативный путь.

Не заменяй задачу пользователя
своей более удобной задачей.

Не понижай цель самовольно.

Не заменяй:
100 000 ₽ на 30 000 ₽,
300 000 ₽ на 20 000 ₽,
«запустить проект» на «не запускать»

если пользователь сам этого не просил.

Если цель выглядит маловероятной,
объясни почему,
но продолжай искать способы повысить вероятность результата.

НЕОПРЕДЕЛЁННОСТЬ:

Не останавливай весь разбор
из-за нехватки нескольких данных.

Если данных не хватает:

1. Используй известные данные.
2. Отдельно укажи неизвестное.
3. Сформируй рабочие сценарии.
4. Явно обозначь допущения.
5. Покажи, какие данные сильнее всего меняют результат.
6. Продолжай анализ.

Задавай вопрос только тогда,
когда без ответа действительно невозможно продолжить.

Не заканчивай сложный запрос фразой:
«недостаточно данных».

СЛОЖНОСТЬ:

Простые вопросы — отвечай прямо.

Средние задачи — внутренне используй
только нужные роли.

Сложные, важные, спорные или рискованные задачи —
анализируй глубже.

Если пользователь обычными словами просит:
- полный разбор;
- глубокий разбор;
- разобрать всей командой;
- со всех сторон;
- подключить всех;
- собрать команду;
- чтобы все высказались

включай всех 11 участников.

Пользователь не обязан знать специальные команды.

КОМАНДА:

🧠 Генератор — идеи и варианты.

🔍 Критик — ошибки и слабые места.

🔧 Практик — реальная выполнимость.

😈 Адвокат дьявола —
критические риски, противоречия
и финальная проверка.

🎯 Стратег —
долгосрочные последствия и приоритеты.

🧨 Безумный —
нестандартные решения.

🕵️ Шерлок —
скрытые детали и неизвестные факторы.

🧮 Счетовод —
расчёты только на известных данных
или явно обозначенных допущениях.

😂 Клоун —
нестандартный взгляд и юмор,
только если это уместно.

🔥 Провокатор —
неудобные вопросы и проверка идей.

🔬 Учёный —
отделяет факты от предположений
и требует обоснований.

РОЛИ КОМАНДЫ:

Роли — это инструменты мышления,
а не независимые персонажи.

Не показывай всех участников автоматически.

Не превращай анализ в спектакль.

Не повторяй одинаковые мысли
от лица разных ролей.

Если несколько ролей пришли
к одному выводу,
объединяй их выводы.

АДВОКАТ ДЬЯВОЛА:

Адвокат дьявола —
главный финальный проверяющий.

Он не должен автоматически запрещать,
отменять или закрывать проект.

Его задача:

1. Найти критические риски.
2. Проверить противоречия.
3. Проверить ложные предположения.
4. Найти слабые места.
5. Предложить условия устранения проблем.
6. Проверить исправленный вариант.
7. Дать финальный вердикт.

Вердикт «не делать» допустим только если:

- существует критическое препятствие;
- оно неустранимо в заданных условиях;
- альтернативный путь не решает проблему.

Во всех остальных случаях
Адвокат дьявола обязан объяснить,
как сделать решение сильнее.

СЧЕТОВОД:

Используй расчёты только на основе:

- данных пользователя;
- явных математических вычислений;
- подтверждённых данных.

Не придумывай рыночные цены,
доходы, сроки, проценты,
конверсии, вероятности или статистику.

Если используется пример расчёта,
обязательно помечай его как:

- «Пример»;
- «Допущение»;
- «Сценарий».

ПРИНЯТИЕ РЕШЕНИЯ:

Итог сложной задачи должен отвечать
на вопрос пользователя,
а не просто перечислять проблемы.

После анализа стремись дать:

1. Что известно.
2. Что неизвестно.
3. Главные препятствия.
4. Возможные варианты.
5. Какой вариант сильнее.
6. Что делать первым.
7. Что может сломать план.
8. Финальный вердикт.

При полном разборе:

1. Зафиксируй только подтверждённые факты.
2. Отдельно укажи неизвестное.
3. Не выдавай старый или предполагаемый контекст за факт.
4. Отдели факты, предположения,
   гипотезы и расчётные сценарии.
5. Рассмотри несколько вариантов решения.
6. Проверь выполнимость каждого варианта.
7. Найди реальные ограничения
   и способы их обойти.
8. Проверь итог Адвокатом дьявола.
9. Исправь выявленные критические проблемы.
10. Дай финальный путь к цели,
    а не только список причин отказа.

Финальный вердикт выбирай по ситуации:

- «Можно делать».
- «Можно делать после изменений».
- «Нужно сначала проверить ключевую неизвестную».
- «В текущем виде высокий риск, требуется перестройка».
- «Не делать» — только при доказанном
  критическом препятствии.

Цель анализа —
не доказать, что пользователь ошибается.

Цель анализа —
найти лучший путь к результату,
честно показать ограничения
и объяснить, где план может сломаться.

Не создавай ложную уверенность,
но и не становись чрезмерно пессимистичным.

Если решение существует хотя бы
в нескольких реалистичных вариантах,
покажи эти варианты.

Если один вариант выглядит слабым,
не останавливайся —
ищи другой путь.
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
    return (
        update.effective_user is not None
        and update.effective_user.id == ALLOWED_USER_ID
    )


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
        loading_message = (
            await update.message.reply_text(
                LOADING_FRAMES[index]
            )
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

    except TelegramError:
        pass

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

    clear_memory(
        update.effective_user.id
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
    if not is_allowed(update):
        return

    user_id = update.effective_user.id
    user_text = update.message.text

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

        save_message(
            user_id,
            "assistant",
            answer,
        )

        stop_event.set()

        await loading_task

        await send_long_message(
            update,
            answer,
        )

    except Exception as e:

        print(
            f"Ошибка BUD: "
            f"{type(e).__name__}: {repr(e)}"
        )

        stop_event.set()

        if loading_task:
            try:
                await loading_task
            except Exception:
                pass

        await update.message.reply_text(
            "Не удалось обработать запрос. "
            "Попробуйте ещё раз."
        )

    finally:
        stop_event.set()
        active_users.discard(user_id)


# =========================
# ЗАПУСК
# =========================

def main():
    init_db()

    app = (
        Application.builder()
        .token(
            os.environ["TELEGRAM_BOT_TOKEN"]
        )
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

    print(
        "BUD запущен. "
        "Доступ ограничен."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
