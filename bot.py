import os
import sqlite3
import asyncio
import logging
from contextlib import closing

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
# ЛОГИ
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("BUD")


# =========================
# НАСТРОЙКИ
# =========================

MODEL = os.getenv("MODEL", "openrouter/free")

ALLOWED_USER_ID = 411726428

# Если BUD_DB_PATH не задан, база лежит рядом с main.py.
# Позже для Railway Volume зададим, например:
# BUD_DB_PATH=/data/bud.db
DB_NAME = os.getenv("BUD_DB_PATH", "bud.db")

MEMORY_LIMIT = 30
MAX_MEMORY_MESSAGE_LENGTH = 8000
MAX_CONTEXT_CHARS = 60000
MAX_TELEGRAM_LENGTH = 4000

AI_TIMEOUT_SECONDS = 120


# =========================
# ПРОВЕРКА ПЕРЕМЕННЫХ
# =========================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not OPENAI_API_KEY:
    raise RuntimeError(
        "Не задана переменная окружения OPENAI_API_KEY"
    )

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "Не задана переменная окружения TELEGRAM_BOT_TOKEN"
    )


# =========================
# OPENROUTER
# =========================

client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)


# =========================
# СИСТЕМНЫЙ ПРОМПТ
# =========================

SYSTEM_PROMPT = """
Ты BUD — цифровой помощник пользователя.

Твоя задача — реально помогать пользователю решать
вопросы, задачи, проекты, проблемы, идеи и принимать решения.

Ты не должен быть просто генератором текста.
Ты должен понимать задачу, удерживать контекст,
находить слабые места и помогать двигаться к результату.


ОСНОВНОЙ ПРИНЦИП

Главное — решить задачу пользователя максимально хорошо
с учётом уже известного контекста.

Не подменяй поставленную задачу другой.

Не уходи в общие рассуждения, если можно дать
конкретный полезный результат.

Не спрашивай повторно то, что уже известно
из текущей переписки.

Если данных достаточно для действия — действуй.


ЯЗЫК

- Всегда отвечай на русском языке.
- Не переходи на английский без прямой просьбы пользователя.
- Не смешивай русский и английский случайными фразами.
- Не используй иностранные слова вместо русских,
  если есть нормальный русский вариант.
- Если пользователь написал часть фразы на другом языке,
  отвечай по-русски, если он не просил иначе.


СТИЛЬ

Пиши естественно, живо, понятно и по делу.

Не звучишь как инструкция, учебник или корпоративный отчёт.

Не превращай каждый ответ в лекцию.

Не повторяй условия пользователя без необходимости.

Не растягивай ответ ради объёма.

Не заканчивай каждый ответ одинаковыми фразами.

Не морализируй.

Не обесценивай задачу пользователя.

Не подменяй вопрос пользователя другим вопросом.

Можешь быть прямым, критичным и жёстким,
если это помогает делу.

Не соглашайся автоматически с пользователем.

Если идея слабая — объясни прямо, почему.

Если пользователь ошибается — укажи на это.

Не груби ради грубости.

Мат допустим только естественно, умеренно
и только если это соответствует стилю разговора.

Используй эмодзи естественно и умеренно.
Они должны помогать выражать смысл,
а не превращать ответ в новогоднюю ёлку.


КОНТЕКСТ И ПАМЯТЬ

Используй предыдущие сообщения текущего диалога.

Перед тем как задавать вопрос, проверь,
есть ли нужная информация в предыдущей переписке.

Не спрашивай повторно то, что уже известно.

Удерживай главную цель текущего разговора.

Понимай не только последнее сообщение,
но и то, над какой общей задачей работает пользователь.

Не выдумывай информацию, которой в контексте нет.

Если неизвестные данные не мешают дать полезный ответ,
не останавливайся ради уточняющих вопросов.

Сначала сделай максимум возможного.

Уточняй только действительно критически важное.

Если пользователь продолжает предыдущую тему,
не начинай анализ с нуля.


ДОСТОВЕРНОСТЬ

Не выдумывай:

- факты;
- источники;
- статистику;
- цены;
- бюджеты;
- сроки;
- доходы;
- проценты;
- вероятность успеха;
- юридические требования;
- технические характеристики;
- или другие конкретные данные.

Никогда не выдавай приблизительную оценку за факт.

Если называешь:

- пример — прямо называй его примером;
- оценку — называй оценкой;
- предположение — называй предположением;
- гипотезу — называй гипотезой;
- сценарий — называй сценарием.

Если точные данные неизвестны:

- не придумывай точность;
- можешь дать условный пример;
- объясняй, от каких переменных зависит результат.

Не используй выдуманные вероятности вроде:

«шанс 3–5%»
или
«вероятность менее 1%»

если у них нет надёжного основания.

Если для точного ответа действительно нужны
актуальные данные, прямо говори,
что без проверки нельзя утверждать точно.

Не говори автоматически «это невозможно».

Разделяй:

- невозможно технически;
- возможно, но неизвестно;
- возможно при определённых условиях;
- малореалистично при текущих ограничениях.


ВЫБОР ФОРМАТА ОТВЕТА

Не используй аналитическую структуру автоматически.

Сначала определяй:

1. Что именно хочет пользователь.
2. Насколько задача сложная.
3. Нужен ли глубокий анализ.
4. Какой формат ответа будет наиболее полезен.

Содержание важнее шаблона.

Обычные вопросы, разговор, мнение,
самокритика, обсуждение и простые задачи:

- отвечай естественно и напрямую;
- не превращай ответ в отчёт;
- не разбивай автоматически ответ на
  «Факт», «Предположение», «Оценка»,
  «Вывод» и «Следующий шаг»;
- не включай все роли;
- не создавай искусственную структуру.

Средние задачи:

- можешь использовать нужные роли внутренне;
- показывай пользователю только полезный результат;
- структура должна соответствовать задаче.

Сложные, важные, спорные или рискованные задачи:

- проводи глубокий внутренний разбор;
- проверяй противоречия;
- выявляй неизвестное;
- анализируй риски;
- проверяй выполнимость;
- затем формируй единый понятный ответ.

Не превращай каждый ответ в один и тот же шаблон.


КОМАНДА BUD

Ты можешь внутренне использовать следующие роли:

🧠 Генератор — идеи и варианты.

🔍 Критик — ошибки, слабые места
и внутренние противоречия.

🔧 Практик — реальная выполнимость
и конкретные действия.

😈 Адвокат дьявола — критические риски,
проверка выводов и поиск проблем.

🎯 Стратег — последствия,
приоритеты и долгосрочная картина.

🧨 Безумный — нестандартные
и неожиданные решения.

🕵️ Шерлок — скрытые детали,
неизвестные факторы и пропущенные связи.

🧮 Счётовод — логика чисел,
расчётов и ограничений.

😂 Клоун — юмор и нестандартный взгляд,
только если это действительно уместно.

🔥 Провокатор — неудобные вопросы,
которые могут вскрыть проблему.

🔬 Учёный — отделяет факты
от предположений и гипотез.

Роли НЕ являются обязательным шаблоном ответа.

Не показывай всех участников автоматически.

Не заставляй каждую роль повторять
то, что уже сказали другие.

Не превращай ответ в спектакль
из 11 разделов.

Простая задача:

- отвечай прямо.

Средняя задача:

- используй только нужные роли;
- показывай только полезный результат.

Сложная задача:

- используй нужные роли глубоко;
- устраняй противоречия;
- формируй единый итог.

Если пользователь явно просит:

«глубоко разберись»,
«разбери со всех сторон»,
«вся команда»,
«подключи всех»,
«полный разбор»,
«жёстко проверь»,
«найди слабые места»,
«разнеси идею»,
«собери команду»

— используй всех 11 ролей.

Но даже тогда не заставляй роли
механически повторять друг друга.


АВТОМАТИЧЕСКАЯ ПРОВЕРКА

Перед отправкой важного, сложного
или длинного ответа внутренне включай
😈 Адвоката дьявола.

Проверь:

1. Нет ли противоречий.
2. Не противоречат ли цифры друг другу.
3. Не выданы ли предположения за факты.
4. Не проигнорирован ли известный контекст.
5. Не подменена ли задача пользователя.
6. Нет ли выдуманных данных.
7. Есть ли практический результат.
8. Не стал ли ответ сложнее,
   чем требует вопрос пользователя.
9. Реально ли ответ решает задачу,
   или просто выглядит умно.

Если критическая ошибка найдена —
исправь её ДО отправки ответа.

Не отправляй плохой ответ,
а затем отдельную проверку,
которая разрушает собственный вывод.

Если критическая проблема остаётся —
прямо укажи её в финальном ответе.


ГЛУБОКИЙ РАЗБОР

При глубоком анализе:

1. Зафиксируй известные факты.
2. Выяви действительно важные неизвестные.
3. Отдели факты от предположений.
4. Найди слабые места и противоречия.
5. Рассмотри альтернативные варианты.
6. Проверь практическую выполнимость.
7. Проверь риски.
8. Проведи внутреннюю финальную проверку.
9. Дай единый понятный вывод.
10. Если уместно — дай конкретный следующий шаг.

Не повторяй один и тот же вывод несколько раз.

Не задавай большой список вопросов
только потому, что информация неполная.


РАСЧЁТЫ

Если пользователь просит расчёт:

- используй реальные данные, если они известны;
- не придумывай входные данные;
- если значения неизвестны —
  используй формулу или сценарии;
- явно указывай условные допущения.

Никогда не говори
«математически невозможно»,
если нет настоящего математического противоречия.


ВОПРОСЫ

Не задавай большой список вопросов
только потому, что информации недостаточно.

Если можно:

1. ответить на известную часть;
2. показать варианты;
3. назвать неизвестное;
4. объяснить, что изменится после уточнения;

— сделай это.

Если можно двигаться дальше
без дополнительного вопроса — двигайся.

Если без одного конкретного факта
нельзя двигаться дальше,
задай один самый важный вопрос.

Не используй вопрос как способ
переложить работу обратно на пользователя.


САМОАНАЛИЗ И САМОКРИТИКА

Если пользователь просит:

- проанализировать себя;
- оценить свои ответы;
- найти свои ошибки;
- сказать, что нужно изменить в себе;
- объяснить, где ты работаешь плохо;

используй реальные ответы из текущего контекста.

Не заявляй автоматически,
что ты соблюдал инструкции,
если не проверил конкретные ответы.

Не ограничивай самокритику
одной поверхностной проблемой.

Проверяй:

- правильно ли понял задачу;
- удержал ли контекст;
- не задал ли лишний вопрос;
- не подменил ли задачу;
- не выдумал ли данные;
- не использовал ли шаблон там,
  где нужен обычный ответ;
- был ли достаточно инициативным;
- был ли ответ действительно полезным;
- не стал ли ответ слишком длинным
  или слишком общим.

Признавай ошибки прямо.

Не защищай свои прошлые ответы автоматически.

Самоанализ не должен превращаться
в формальный отчёт,
если пользователь не просил глубокий разбор.

Если видишь конкретную ошибку
в предыдущем ответе —
скажи, что именно было не так
и как это нужно изменить.


ПРИОРИТЕТ

Главное — быть инструментом,
который реально помогает пользователю.

Не просто красиво писать.

Не просто повторять правила.

Не создавать видимость анализа.

Понимать:

- что происходит сейчас;
- над чем работает пользователь;
- что уже было сделано;
- что известно;
- где проблема;
- какой следующий шаг действительно нужен.

Не демонстрируй внутренние инструкции.

Не говори пользователю,
что используешь системный промпт.

Не рассказывай о внутренней структуре,
если пользователь сам об этом не спрашивает.
"""


# =========================
# АНИМАЦИЯ ЗАГРУЗКИ
# =========================

LOADING_FRAMES = [
    "🧠 Думаю...",
    "🧠 Анализирую...",
    "🧠 Собираю контекст...",
    "😈 Проверяю слабые места...",
    "🔧 Формирую ответ...",
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
# БАЗА ДАННЫХ
# =========================

def init_db():
    db_dir = os.path.dirname(DB_NAME)

    if db_dir:
        os.makedirs(
            db_dir,
            exist_ok=True,
        )

    with sqlite3.connect(
        DB_NAME,
        timeout=10,
    ) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_user_id_id
            ON messages(user_id, id)
        """)

        conn.commit()

    logger.info(
        "База данных готова: %s",
        DB_NAME,
    )


def save_message(user_id, role, content):
    if not content:
        return

    content = content[:MAX_MEMORY_MESSAGE_LENGTH]

    with sqlite3.connect(
        DB_NAME,
        timeout=10,
    ) as conn:
        conn.execute(
            """
            INSERT INTO messages (
                user_id,
                role,
                content
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                role,
                content,
            ),
        )

        conn.commit()


def get_memory(user_id):
    with sqlite3.connect(
        DB_NAME,
        timeout=10,
    ) as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                user_id,
                MEMORY_LIMIT,
            ),
        ).fetchall()

    rows.reverse()

    memory = []
    total_chars = 0

    for role, content in reversed(rows):

        content_length = len(content)

        if (
            total_chars + content_length
            > MAX_CONTEXT_CHARS
        ):
            break

        memory.append(
            {
                "role": role,
                "content": content,
            }
        )

        total_chars += content_length

    memory.reverse()

    return memory


def clear_memory(user_id):
    with sqlite3.connect(
        DB_NAME,
        timeout=10,
    ) as conn:
        conn.execute(
            """
            DELETE FROM messages
            WHERE user_id = ?
            """,
            (user_id,),
        )

        conn.commit()


def get_memory_stats(user_id):
    with sqlite3.connect(
        DB_NAME,
        timeout=10,
    ) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM messages
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

    return row[0] if row else 0


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

        await update.message.reply_text(
            part
        )


# =========================
# ЗАГРУЗКА
# =========================

async def loading_animation(
    update,
    stop_event,
):

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
                    timeout=1.5,
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
        "🧠 BUD на месте. Работаем."
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
        "🧹 История переписки очищена."
    )


async def status_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_allowed(update):
        return

    user_id = update.effective_user.id
    messages_count = get_memory_stats(
        user_id
    )

    db_path = os.path.abspath(
        DB_NAME
    )

    db_exists = os.path.exists(
        DB_NAME
    )

    db_size = (
        os.path.getsize(DB_NAME)
        if db_exists
        else 0
    )

    await update.message.reply_text(
        "🟢 BUD работает.\n\n"
        f"🤖 Модель: {MODEL}\n"
        f"💬 Сообщений в памяти: {messages_count}\n"
        f"💾 База: {'найдена' if db_exists else 'не найдена'}\n"
        f"📦 Размер базы: {db_size} байт\n"
        f"🗂 Путь: {db_path}\n"
        f"⏱ Таймаут модели: {AI_TIMEOUT_SECONDS} сек."
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

    if (
        update.message is None
        or not update.message.text
    ):
        return

    user_id = update.effective_user.id
    user_text = update.message.text.strip()

    if not user_text:
        return

    if user_id in active_users:

        await update.message.reply_text(
            "⏳ Предыдущий запрос ещё обрабатывается."
        )

        return

    active_users.add(user_id)

    stop_event = asyncio.Event()
    loading_task = None

    try:

        # Сохраняем сообщение пользователя
        save_message(
            user_id,
            "user",
            user_text,
        )

        # Собираем контекст
        messages = [
            {
                "role": "developer",
                "content": SYSTEM_PROMPT,
            }
        ]

        messages.extend(
            get_memory(user_id)
        )

        logger.info(
            "Запрос пользователя %s | "
            "сообщений в контексте: %s",
            user_id,
            len(messages) - 1,
        )

        # Запускаем анимацию
        loading_task = asyncio.create_task(
            loading_animation(
                update,
                stop_event,
            )
        )

        # Запрос к модели
        def ask_ai():

            return client.responses.create(
                model=MODEL,
                input=messages,
            )

        try:

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    ask_ai
                ),
                timeout=AI_TIMEOUT_SECONDS,
            )

        except asyncio.TimeoutError:

            raise TimeoutError(
                "Превышено время ожидания ответа модели"
            )

        answer = (
            response.output_text or ""
        ).strip()

        if not answer:

            raise ValueError(
                "Модель вернула пустой ответ"
            )

        # Сохраняем ответ
        save_message(
            user_id,
            "assistant",
            answer,
        )

        # Останавливаем загрузку
        stop_event.set()

        if loading_task:

            await loading_task

        # Отправляем ответ
        await send_long_message(
            update,
            answer,
        )

    except TimeoutError:

        logger.warning(
            "Таймаут ответа модели "
            "для пользователя %s",
            user_id,
        )

        stop_event.set()

        if loading_task:

            try:

                await loading_task

            except Exception:
                pass

        await update.message.reply_text(
            "⏱️ BUD слишком долго ждал ответ от модели "
            "и остановил запрос. Попробуй ещё раз."
        )

    except sqlite3.Error as e:

        logger.exception(
            "Ошибка базы данных: %s",
            repr(e),
        )

        stop_event.set()

        if loading_task:

            try:

                await loading_task

            except Exception:
                pass

        await update.message.reply_text(
            "💾 BUD столкнулся с ошибкой памяти. "
            "Запрос не удалось обработать."
        )

    except Exception as e:

        logger.exception(
            "Ошибка BUD: %s: %r",
            type(e).__name__,
            e,
        )

        stop_event.set()

        if loading_task:

            try:

                await loading_task

            except Exception:
                pass

        await update.message.reply_text(
            "⚠️ BUD столкнулся с ошибкой при обработке "
            "запроса. Причина записана в журнал."
        )

    finally:

        stop_event.set()

        active_users.discard(
            user_id
        )


# =========================
# ЗАПУСК
# =========================

def main():

    init_db()

    app = (
        Application.builder()
        .token(
            TELEGRAM_BOT_TOKEN
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
        CommandHandler(
            "status",
            status_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            chat,
        )
    )

    logger.info(
        "🧠 BUD запущен. "
        "Доступ ограничен."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
