import os
import sqlite3
import asyncio
import logging

from openai import OpenAI
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatAction
from telegram.error import BadRequest, TelegramError, Conflict
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# =========================
# НАСТРОЙКИ
# =========================

MODEL = os.getenv(
    "MODEL",
    "openrouter/free",
)

FALLBACK_MODEL = os.getenv(
    "FALLBACK_MODEL",
    MODEL,
)

MODEL_RETRIES = 2

ALLOWED_USER_ID = int(
    os.getenv(
        "ALLOWED_USER_ID",
        "411726428",
    )
)

DB_NAME = "bud.db"

MEMORY_RECENT_MESSAGES = 20

MEMORY_COMPRESS_TRIGGER = 32

MAX_MEMORY_MESSAGE_LENGTH = 8000

MAX_CONTEXT_CHARS = 45000

MAX_SUMMARY_LENGTH = 12000

MAX_TELEGRAM_LENGTH = 4000


# =========================
# ЛОГИ
# =========================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger("BUD")

logging.getLogger(
    "httpx"
).setLevel(logging.WARNING)

logging.getLogger(
    "httpx2"
).setLevel(logging.WARNING)


# =========================
# OPENROUTER
# =========================

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY",
)

if not OPENAI_API_KEY:

    raise RuntimeError(
        "Не задана переменная "
        "OPENAI_API_KEY"
    )


client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=(
        "https://openrouter.ai/api/v1"
    ),
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
# ПРОМПТ ДЛЯ СВОДНОЙ ПАМЯТИ
# =========================

SUMMARY_PROMPT = """
Ты обновляешь краткую память цифрового помощника BUD.

Твоя задача — сжать старую часть переписки так,
чтобы сохранить только информацию,
которая может быть важна в следующих сообщениях.

Сохраняй:

- главные цели пользователя;
- активные проекты;
- уже принятые решения;
- важные ограничения;
- факты, которые пользователь сообщил;
- важные договорённости;
- незавершённые задачи;
- ошибки, которые нельзя повторять;
- контекст, который понадобится для продолжения разговора.

Не сохраняй:

- пустую болтовню;
- повторения;
- временные детали без дальнейшей пользы;
- свои догадки о пользователе;
- выдуманные факты.

Если информация является предположением,
явно отмечай это как предположение.

Не добавляй никакой новой информации.

Не обращайся к пользователю.

Не пиши вступление.

Создай компактную рабочую сводку.
"""


# =========================
# КНОПКИ И МЕНЮ
# =========================

MENU_TEXT = "🧠 Меню"

BUTTON_CHAT = "💬 Продолжить разговор"
BUTTON_MEMORY = "🧠 Память"
BUTTON_TEAM = "👥 Команда BUD"
BUTTON_PROJECTS = "📋 Что мы делаем"
BUTTON_SETTINGS = "⚙️ Настройки"
BUTTON_CLEAR_MEMORY = "🧹 Очистить память"


def get_main_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                BUTTON_CHAT,
            ],
            [
                BUTTON_MEMORY,
                BUTTON_PROJECTS,
            ],
            [
                BUTTON_TEAM,
                BUTTON_SETTINGS,
            ],
            [
                BUTTON_CLEAR_MEMORY,
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=(
            "Напиши, что нужно сделать..."
        ),
    )


def get_start_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🚀 Начать",
                    callback_data="start_work",
                ),
                InlineKeyboardButton(
                    "🧠 Что ты умеешь",
                    callback_data="what_can_do",
                ),
            ],
        ]
    )


def get_clear_memory_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🧹 Да, очистить",
                    callback_data="clear_memory_confirm",
                ),
            ],
            [
                InlineKeyboardButton(
                    "↩️ Отмена",
                    callback_data="clear_memory_cancel",
                ),
            ],
        ]
    )


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
        and update.effective_user.id
        == ALLOWED_USER_ID
    )


# =========================
# БАЗА ДАННЫХ
# =========================

def init_db():

    with sqlite3.connect(
        DB_NAME
    ) as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER
                    PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER
                    NOT NULL,

                role TEXT
                    NOT NULL,

                content TEXT
                    NOT NULL,

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_messages_user_id

            ON messages (
                user_id,
                id
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_state (
                user_id INTEGER
                    PRIMARY KEY,

                summary TEXT
                    NOT NULL
                    DEFAULT '',

                updated_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)


def save_message(
    user_id,
    role,
    content,
):

    content = (
        content
        or ""
    )

    content = content[
        :MAX_MEMORY_MESSAGE_LENGTH
    ]

    with sqlite3.connect(
        DB_NAME
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


def get_message_count(
    user_id,
):

    with sqlite3.connect(
        DB_NAME
    ) as conn:

        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM messages
            WHERE user_id = ?
            """,
            (
                user_id,
            ),
        ).fetchone()

    return row[0]


def get_recent_messages(
    user_id,
    limit,
):

    with sqlite3.connect(
        DB_NAME
    ) as conn:

        rows = conn.execute(
            """
            SELECT
                id,
                role,
                content

            FROM messages

            WHERE user_id = ?

            ORDER BY id DESC

            LIMIT ?
            """,
            (
                user_id,
                limit,
            ),
        ).fetchall()

    rows.reverse()

    return rows


def get_old_messages_for_compression(
    user_id,
):

    with sqlite3.connect(
        DB_NAME
    ) as conn:

        rows = conn.execute(
            """
            SELECT
                id,
                role,
                content

            FROM messages

            WHERE user_id = ?

            ORDER BY id DESC

            LIMIT -1
            OFFSET ?
            """,
            (
                user_id,
                MEMORY_RECENT_MESSAGES,
            ),
        ).fetchall()

    rows.reverse()

    return rows


def get_memory_summary(
    user_id,
):

    with sqlite3.connect(
        DB_NAME
    ) as conn:

        row = conn.execute(
            """
            SELECT summary

            FROM memory_state

            WHERE user_id = ?
            """,
            (
                user_id,
            ),
        ).fetchone()

    if not row:

        return ""

    return row[0] or ""


def save_memory_summary(
    user_id,
    summary,
):

    summary = (
        summary
        or ""
    )

    summary = summary[
        :MAX_SUMMARY_LENGTH
    ]

    with sqlite3.connect(
        DB_NAME
    ) as conn:

        conn.execute(
            """
            INSERT INTO memory_state (
                user_id,
                summary,
                updated_at
            )
            VALUES (
                ?,
                ?,
                CURRENT_TIMESTAMP
            )

            ON CONFLICT(user_id)

            DO UPDATE SET

                summary = excluded.summary,

                updated_at =
                    CURRENT_TIMESTAMP
            """,
            (
                user_id,
                summary,
            ),
        )


def delete_messages_by_ids(
    user_id,
    message_ids,
):

    if not message_ids:

        return

    placeholders = (
        ",".join(
            "?"
            for _ in message_ids
        )
    )

    with sqlite3.connect(
        DB_NAME
    ) as conn:

        conn.execute(
            f"""
            DELETE FROM messages

            WHERE user_id = ?

            AND id IN (
                {placeholders}
            )
            """,
            (
                user_id,
                *message_ids,
            ),
        )


def clear_memory(
    user_id,
):

    with sqlite3.connect(
        DB_NAME
    ) as conn:

        conn.execute(
            """
            DELETE FROM messages
            WHERE user_id = ?
            """,
            (
                user_id,
            ),
        )

        conn.execute(
            """
            DELETE FROM memory_state
            WHERE user_id = ?
            """,
            (
                user_id,
            ),
        )


# =========================
# ПАМЯТЬ
# =========================

def format_memory_for_summary(
    rows,
):

    parts = []

    for _id, role, content in rows:

        if role == "user":

            label = "ПОЛЬЗОВАТЕЛЬ"

        elif role == "assistant":

            label = "BUD"

        else:

            label = role.upper()

        parts.append(
            f"{label}:\n{content}"
        )

    return (
        "\n\n"
        .join(parts)
    )


def build_context_messages(
    user_id,
):

    summary = get_memory_summary(
        user_id
    )

    recent_rows = get_recent_messages(
        user_id,
        MEMORY_RECENT_MESSAGES,
    )

    messages = [
        {
            "role": "developer",
            "content": SYSTEM_PROMPT,
        }
    ]

    if summary.strip():

        messages.append(
            {
                "role": "developer",
                "content": (
                    "ВАЖНАЯ СВОДНАЯ ПАМЯТЬ "
                    "ПРЕДЫДУЩЕГО ДИАЛОГА:\n\n"
                    f"{summary}"
                ),
            }
        )

    for _id, role, content in recent_rows:

        messages.append(
            {
                "role": role,
                "content": content,
            }
        )

    def context_size():

        total = 0

        for message in messages:

            content = (
                message.get(
                    "content",
                    "",
                )
                or ""
            )

            total += len(content)

        return total

    while (
        context_size()
        > MAX_CONTEXT_CHARS
        and len(messages) > 3
    ):

        messages.pop(2)

    return messages


# =========================
# ЗАПРОС К МОДЕЛИ
# =========================

def extract_output_text(
    response,
):

    answer = (
        getattr(
            response,
            "output_text",
            "",
        )
        or ""
    )

    return answer.strip()


def ask_model_sync(
    messages,
    model,
):

    response = client.responses.create(
        model=model,
        input=messages,
    )

    answer = extract_output_text(
        response
    )

    if answer:

        return answer

    logger.warning(
        "Модель вернула пустой output_text | "
        "model=%s | response_id=%s | "
        "status=%s",
        model,
        getattr(
            response,
            "id",
            None,
        ),
        getattr(
            response,
            "status",
            None,
        ),
    )

    raise ValueError(
        "Модель вернула пустой ответ"
    )


async def ask_ai_with_retries(
    messages,
):

    models = [
        MODEL,
    ]

    if (
        FALLBACK_MODEL
        and FALLBACK_MODEL != MODEL
    ):

        models.append(
            FALLBACK_MODEL
        )

    last_error = None

    for model in models:

        for attempt in range(
            1,
            MODEL_RETRIES + 1,
        ):

            try:

                logger.info(
                    "Запрос к модели | "
                    "model=%s | "
                    "попытка=%s/%s",
                    model,
                    attempt,
                    MODEL_RETRIES,
                )

                answer = (
                    await asyncio.to_thread(
                        ask_model_sync,
                        messages,
                        model,
                    )
                )

                return answer

            except Exception as e:

                last_error = e

                logger.warning(
                    "Неудачный запрос к модели | "
                    "model=%s | "
                    "попытка=%s/%s | "
                    "ошибка=%s: %s",
                    model,
                    attempt,
                    MODEL_RETRIES,
                    type(e).__name__,
                    repr(e),
                )

                if (
                    attempt
                    < MODEL_RETRIES
                ):

                    await asyncio.sleep(
                        attempt
                    )

    raise RuntimeError(
        "Все попытки получить ответ "
        "от модели завершились ошибкой"
    ) from last_error


# =========================
# СЖАТИЕ ПАМЯТИ
# =========================

async def compress_memory_if_needed(
    user_id,
):

    count = get_message_count(
        user_id
    )

    if (
        count
        <= MEMORY_COMPRESS_TRIGGER
    ):

        return

    old_rows = (
        get_old_messages_for_compression(
            user_id
        )
    )

    if not old_rows:

        return

    old_text = (
        format_memory_for_summary(
            old_rows
        )
    )

    existing_summary = (
        get_memory_summary(
            user_id
        )
    )

    summary_input = []

    if existing_summary.strip():

        summary_input.append(
            {
                "role": "developer",
                "content": (
                    "Текущая сводная память:\n\n"
                    f"{existing_summary}"
                ),
            }
        )

    summary_input.append(
        {
            "role": "developer",
            "content": SUMMARY_PROMPT,
        }
    )

    summary_input.append(
        {
            "role": "user",
            "content": (
                "Вот новая старая часть "
                "переписки, которую нужно "
                "добавить в сводную память:\n\n"
                f"{old_text}"
            ),
        }
    )

    try:

        summary = (
            await ask_ai_with_retries(
                summary_input
            )
        )

        if not summary.strip():

            return

        save_memory_summary(
            user_id,
            summary,
        )

        message_ids = [
            row[0]
            for row in old_rows
        ]

        delete_messages_by_ids(
            user_id,
            message_ids,
        )

        logger.info(
            "Память сжата | "
            "user_id=%s | "
            "сжато сообщений=%s",
            user_id,
            len(message_ids),
        )

    except Exception:

        logger.exception(
            "Не удалось сжать память | "
            "user_id=%s",
            user_id,
        )


# =========================
# ДЛИННЫЕ СООБЩЕНИЯ
# =========================

def split_message(
    text,
):

    if (
        len(text)
        <= MAX_TELEGRAM_LENGTH
    ):

        return [text]

    parts = []

    while text:

        if (
            len(text)
            <= MAX_TELEGRAM_LENGTH
        ):

            parts.append(
                text
            )

            break

        split_at = text.rfind(
            "\n",
            0,
            MAX_TELEGRAM_LENGTH,
        )

        if (
            split_at
            < MAX_TELEGRAM_LENGTH // 2
        ):

            split_at = text.rfind(
                " ",
                0,
                MAX_TELEGRAM_LENGTH,
            )

        if (
            split_at
            < MAX_TELEGRAM_LENGTH // 2
        ):

            split_at = (
                MAX_TELEGRAM_LENGTH
            )

        parts.append(
            text[
                :split_at
            ].rstrip()
        )

        text = text[
            split_at:
        ].lstrip()

    return parts


async def send_long_message(
    update,
    text,
):

    for part in split_message(
        text
    ):

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
                LOADING_FRAMES[
                    index
                ]
            )
        )

        while (
            not stop_event.is_set()
        ):

            try:

                await (
                    update.effective_chat
                    .send_action(
                        ChatAction.TYPING
                    )
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
            ) % len(
                LOADING_FRAMES
            )

            try:

                await (
                    loading_message
                    .edit_text(
                        LOADING_FRAMES[
                            index
                        ]
                    )
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

                await (
                    loading_message
                    .delete()
                )

            except TelegramError:

                pass


# =========================
# КОМАНДЫ
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_allowed(
        update
    ):

        return

    await (
        update.message.reply_text(
            "🧠 Привет, Андрей.\n\n"
            "Я BUD. Твой личный цифровой помощник.\n\n"
            "Помогаю разбирать задачи, проекты, "
            "идеи и проблемы, искать слабые места "
            "и двигаться к результату.\n\n"
            "Готов. Что делаем?",
            reply_markup=get_start_keyboard(),
        )
    )


async def menu_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_allowed(
        update
    ):

        return

    await (
        update.message.reply_text(
            MENU_TEXT,
            reply_markup=get_main_keyboard(),
        )
    )


async def memory_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_allowed(
        update
    ):

        return

    await (
        update.message.reply_text(
            "⚠️ Ты точно хочешь очистить "
            "память и историю переписки?\n\n"
            "Это действие нельзя отменить.",
            reply_markup=get_clear_memory_keyboard(),
        )
    )


# =========================
# КНОПКИ
# =========================

async def button_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if query is None:

        return

    if (
        query.from_user.id
        != ALLOWED_USER_ID
    ):

        await query.answer()

        return

    await query.answer()

    data = query.data

    if data == "start_work":

        await query.edit_message_text(
            "🚀 Поехали.\n\n"
            "Пиши, что нужно сделать. "
            "Разберёмся."
        )

        await (
            query.message.reply_text(
                MENU_TEXT,
                reply_markup=get_main_keyboard(),
            )
        )

        return

    if data == "what_can_do":

        await query.edit_message_text(
            "🧠 Что умеет BUD\n\n"
            "• Разбирать задачи и проекты\n"
            "• Помогать с кодом и ошибками\n"
            "• Искать слабые места в идеях\n"
            "• Планировать действия\n"
            "• Помнить важный контекст\n"
            "• Работать с командой из 11 экспертов\n"
            "• Проверять решения и риски\n"
            "• Помогать доводить дела до результата"
        )

        return

    if data == "clear_memory_confirm":

        clear_memory(
            query.from_user.id
        )

        await query.edit_message_text(
            "🧹 Готово. Память и история "
            "переписки очищены."
        )

        return

    if data == "clear_memory_cancel":

        await query.edit_message_text(
            "↩️ Очистка отменена. "
            "Память сохранена."
        )

        return


# =========================
# ОБРАБОТКА МЕНЮ
# =========================

async def menu_actions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_allowed(
        update
    ):

        return False

    if (
        update.message is None
        or not update.message.text
    ):

        return False

    user_id = (
        update.effective_user.id
    )

    user_text = (
        update.message.text
    )

    if user_text == BUTTON_CHAT:

        await (
            update.message.reply_text(
                "💬 Продолжаем. "
                "Пиши, что нужно сделать."
            )
        )

        return True

    if user_text == BUTTON_MEMORY:

        summary = get_memory_summary(
            user_id
        )

        recent_rows = get_recent_messages(
            user_id,
            8,
        )

        message_count = get_message_count(
            user_id
        )

        if summary.strip():

            memory_text = (
                "🧠 Что сейчас сохранено в памяти:\n\n"
                f"{summary}"
            )

        else:

            memory_text = (
                "🧠 Отдельная сводная память "
                "пока не создана.\n\n"
                "BUD продолжает удерживать "
                "последние сообщения из переписки."
            )

        memory_text += (
            "\n\n"
            f"📨 Сообщений в истории: "
            f"{message_count}\n"
            f"🧠 Последних сообщений в контексте: "
            f"{len(recent_rows)}"
        )

        await send_long_message(
            update,
            memory_text,
        )

        return True

    if user_text == BUTTON_TEAM:

        await (
            update.message.reply_text(
                "👥 Команда BUD\n\n"
                "🧠 Генератор — идеи и варианты\n"
                "🔍 Критик — ошибки и слабые места\n"
                "🔧 Практик — реальные действия\n"
                "😈 Адвокат дьявола — жёсткая проверка\n"
                "🎯 Стратег — последствия и направление\n"
                "🧨 Безумный — нестандартные решения\n"
                "🕵️ Шерлок — скрытые детали\n"
                "🧮 Счётовод — расчёты и ограничения\n"
                "😂 Клоун — юмор и необычный взгляд\n"
                "🔥 Провокатор — неудобные вопросы\n"
                "🔬 Учёный — факты против предположений\n\n"
                "Для полного разбора напиши:\n"
                "«Подключи всю команду»"
            )
        )

        return True

    if user_text == BUTTON_PROJECTS:

        summary = get_memory_summary(
            user_id
        )

        if summary.strip():

            await (
                update.message.reply_text(
                    "📋 Текущий сохранённый контекст "
                    "работы:\n\n"
                    f"{summary}"
                )
            )

        else:

            await (
                update.message.reply_text(
                    "📋 Пока нет отдельной сводки "
                    "активных задач.\n\n"
                    "Продолжай работу в диалоге, "
                    "и BUD будет удерживать "
                    "контекст переписки."
                )
            )

        return True

    if user_text == BUTTON_SETTINGS:

        await (
            update.message.reply_text(
                "⚙️ Настройки BUD\n\n"
                f"Основная модель: {MODEL}\n"
                f"Запасная модель: {FALLBACK_MODEL}\n"
                f"Последних сообщений в памяти: "
                f"{MEMORY_RECENT_MESSAGES}\n"
                f"Сжатие истории после: "
                f"{MEMORY_COMPRESS_TRIGGER} сообщений\n"
                f"Доступ: только для разрешённого "
                f"пользователя"
            )
        )

        return True

    if user_text == BUTTON_CLEAR_MEMORY:

        await (
            update.message.reply_text(
                "⚠️ Ты точно хочешь очистить "
                "память и историю переписки?\n\n"
                "Это действие нельзя отменить.",
                reply_markup=get_clear_memory_keyboard(),
            )
        )

        return True

    return False


# =========================
# ОБЩЕНИЕ
# =========================

async def chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_allowed(
        update
    ):

        return

    if (
        update.message is None
        or not update.message.text
    ):

        return

    handled = await menu_actions(
        update,
        context,
    )

    if handled:

        return

    user_id = (
        update.effective_user.id
    )

    user_text = (
        update.message.text
    )

    if (
        user_id
        in active_users
    ):

        await (
            update.message.reply_text(
                "⏳ Предыдущий запрос "
                "ещё обрабатывается."
            )
        )

        return

    active_users.add(
        user_id
    )

    stop_event = asyncio.Event()

    loading_task = None

    try:

        save_message(
            user_id,
            "user",
            user_text,
        )

        await (
            compress_memory_if_needed(
                user_id
            )
        )

        messages = (
            build_context_messages(
                user_id
            )
        )

        logger.info(
            "Запрос пользователя %s | "
            "сообщений в контексте: %s | "
            "символов контекста: %s",
            user_id,
            len(messages),
            sum(
                len(
                    message.get(
                        "content",
                        "",
                    )
                    or ""
                )
                for message in messages
            ),
        )

        loading_task = (
            asyncio.create_task(
                loading_animation(
                    update,
                    stop_event,
                )
            )
        )

        answer = (
            await ask_ai_with_retries(
                messages
            )
        )

        if not answer:

            raise ValueError(
                "После всех попыток "
                "получен пустой ответ"
            )

        save_message(
            user_id,
            "assistant",
            answer,
        )

        stop_event.set()

        if loading_task:

            try:

                await loading_task

            except Exception:

                logger.exception(
                    "Ошибка при остановке "
                    "анимации"
                )

        await send_long_message(
            update,
            answer,
        )

        await (
            compress_memory_if_needed(
                user_id
            )
        )

    except Exception as e:

        logger.exception(
            "Ошибка BUD | "
            "user_id=%s | "
            "тип=%s | "
            "ошибка=%r",
            user_id,
            type(e).__name__,
            e,
        )

        stop_event.set()

        if loading_task:

            try:

                await loading_task

            except Exception:

                pass

        try:

            await (
                update.message.reply_text(
                    "⚠️ BUD столкнулся "
                    "с ошибкой при обработке "
                    "запроса. Причина записана "
                    "в журнал."
                )
            )

        except TelegramError:

            pass

    finally:

        stop_event.set()

        active_users.discard(
            user_id
        )


# =========================
# ОБЩИЙ ОБРАБОТЧИК ОШИБОК
# =========================

async def error_handler(
    update,
    context,
):

    error = context.error

    if isinstance(
        error,
        Conflict,
    ):

        logger.error(
            "КОНФЛИКТ TELEGRAM: "
            "одновременно работает "
            "несколько экземпляров BUD. "
            "Остановите лишний процесс."
        )

        return

    logger.exception(
        "Необработанная ошибка "
        "Telegram",
        exc_info=error,
    )


# =========================
# ЗАПУСК
# =========================

def main():

    init_db()

    telegram_token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    if not telegram_token:

        raise RuntimeError(
            "Не задана переменная "
            "TELEGRAM_BOT_TOKEN"
        )

    logger.info(
        "🧠 BUD запускается | "
        "model=%s | "
        "fallback=%s | "
        "user_id=%s",
        MODEL,
        FALLBACK_MODEL,
        ALLOWED_USER_ID,
    )

    app = (
        Application.builder()
        .token(
            telegram_token
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
            "menu",
            menu_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "memory",
            memory_command,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_callback
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

    logger.info(
        "🧠 BUD запущен. "
        "Доступ ограничен."
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":

    main()
