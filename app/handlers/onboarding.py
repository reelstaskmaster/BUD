from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import repositories as repo

QUESTIONS = [
    ("Как BUD должен с тобой общаться?", "communication", ["😎 По-дружески", "😂 С юмором", "🧠 Умно и по делу", "💼 Серьёзно"]),
    ("Какие ответы тебе нравятся?", "answer_style", ["⚡ Короткие", "⚖️ Средние", "📚 Подробные", "🎯 Сразу решение"]),
    ("Что тебе интересно?", "interests", ["🚗 Автомобили", "🤖 Технологии", "💡 Идеи", "📱 Контент", "🎨 Творчество", "💼 Работа", "📚 Учёба"]),
    ("В чём тебе чаще всего помогать?", "help_with", ["Придумывать", "Анализировать", "Объяснять", "Создавать", "Планировать", "Принимать решения"]),
    ("Каким быть, если ты ошибаешься?", "correction_style", ["🔥 Говорить прямо", "🤝 Объяснять мягко", "🧠 Спорить и приводить аргументы", "🤐 Не вмешиваться без необходимости"]),
    ("Что BUD особенно важно запоминать?", "remember", ["❤️ Мои предпочтения", "🎯 Мои цели", "💡 Мои идеи", "📋 Мои проекты", "👥 Важных для меня людей"]),
]


def build_router(*, session_factory: async_sessionmaker[AsyncSession]) -> Router:
    router = Router(name="onboarding")

    @router.message(CommandStart(), F.chat.type == "private")
    async def on_start(message: Message) -> None:
        async with session_factory() as session:
            profile = await repo.get_profile(session, message.chat.id)
            if profile.onboarding_complete:
                await session.commit()
                await message.answer("С возвращением. Пиши текстом, голосом или кидай картинку — я здесь.")
                return
            step = profile.onboarding_step
            await session.commit()
        if step >= len(QUESTIONS):
            await message.answer(
                "✍️ Расскажи о себе своими словами.\n\n"
                "Что тебе нравится, чем увлекаешься, чем занимаешься или что важно для BUD — я сам выделю главное."
            )
            return
        await message.answer("Привет. Давай за минуту настроим BUD под тебя.\n\nВыбирай несколько вариантов, где это подходит.")
        await _send_question(message, step)

    @router.callback_query(F.data.startswith("onb:"))
    async def on_callback(callback: CallbackQuery) -> None:
        parts = (callback.data or "").split(":")
        if len(parts) != 3:
            await callback.answer()
            return
        try:
            step = int(parts[1])
        except ValueError:
            await callback.answer("Некорректный шаг.", show_alert=True)
            return
        action = parts[2]
        if step < 0 or step >= len(QUESTIONS):
            await callback.answer()
            return

        chat_id = callback.message.chat.id
        async with session_factory() as session:
            profile = await repo.get_profile(session, chat_id)
            if profile.onboarding_complete:
                await session.commit()
                await callback.answer()
                return

            # The final "about" button is intentionally tied to question 6's
            # callback, while the stored onboarding step is already 6.
            if action == "about" and profile.onboarding_step == len(QUESTIONS) and step == len(QUESTIONS) - 1:
                await session.commit()
                await callback.message.edit_text(
                    "✍️ Расскажи о себе своими словами.\n\n"
                    "Что тебе нравится, чем увлекаешься, чем занимаешься или что важно для BUD — я сам выделю главное."
                )
                await callback.answer()
                return

            if profile.onboarding_step != step:
                await session.commit()
                await callback.answer("Этот вопрос уже пройден.")
                return
            preferences = dict(profile.preferences or {})
            key = QUESTIONS[step][1]
            selected = list(preferences.get(key) or [])
            options = QUESTIONS[step][2]
            if action == "done":
                if not selected:
                    await callback.answer("Выбери хотя бы один вариант.")
                    return
                profile.onboarding_step = step + 1
                if step + 1 == len(QUESTIONS):
                    await session.commit()
                    await callback.message.edit_text(
                        "6/6 — Готово. Теперь можно рассказать о себе свободным текстом.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="✍️ Рассказать о себе", callback_data=f"onb:{step}:about")],
                        ]),
                    )
                    await callback.answer()
                    return
                await session.commit()
                await callback.message.edit_text(_question_text(step + 1), reply_markup=_keyboard(step + 1, preferences))
                await callback.answer()
                return
            try:
                index = int(action)
            except ValueError:
                await callback.answer("Некорректный вариант.", show_alert=True)
                return
            if index < 0 or index >= len(options):
                await callback.answer("Некорректный вариант.", show_alert=True)
                return
            value = options[index]
            if value in selected:
                selected.remove(value)
            else:
                selected.append(value)
            preferences[key] = selected
            profile.preferences = preferences
            await session.commit()
            await callback.message.edit_text(_question_text(step), reply_markup=_keyboard(step, preferences))
        await callback.answer()

    return router


async def _send_question(message: Message, step: int) -> None:
    await message.answer(_question_text(step), reply_markup=_keyboard(step, {}))


def _question_text(step: int) -> str:
    return f"{step + 1}/{len(QUESTIONS)} — {QUESTIONS[step][0]}"


def _keyboard(step: int, preferences: dict) -> InlineKeyboardMarkup:
    key = QUESTIONS[step][1]
    selected = set(preferences.get(key) or [])
    rows: list[list[InlineKeyboardButton]] = []
    for index, option in enumerate(QUESTIONS[step][2]):
        prefix = "✅ " if option in selected else "▫️ "
        rows.append([InlineKeyboardButton(text=prefix + option, callback_data=f"onb:{step}:{index}")])
    rows.append([InlineKeyboardButton(text="Готово →", callback_data=f"onb:{step}:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
