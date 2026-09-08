from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import repositories as repo


def build_router(*, session_factory: async_sessionmaker[AsyncSession]) -> Router:
    router = Router(name="settings")

    @router.message(Command("settings"), F.chat.type == "private")
    async def settings_command(message: Message) -> None:
        await _send_settings(message, session_factory)

    @router.callback_query(F.data == "settings:open")
    async def settings_open(callback: CallbackQuery) -> None:
        await _edit_settings(callback, session_factory)
        await callback.answer()

    @router.callback_query(F.data == "settings:memory_toggle")
    async def memory_toggle(callback: CallbackQuery) -> None:
        async with session_factory() as session:
            profile = await repo.get_profile(session, callback.message.chat.id)
            profile.memory_enabled = not profile.memory_enabled
            await session.commit()
        await _edit_settings(callback, session_factory)
        await callback.answer("Память включена." if profile.memory_enabled else "Память выключена.")

    @router.callback_query(F.data == "settings:memory")
    async def memory_status(callback: CallbackQuery) -> None:
        await _edit_memory(callback, session_factory)
        await callback.answer()

    @router.callback_query(F.data == "settings:profile")
    async def profile_view(callback: CallbackQuery) -> None:
        async with session_factory() as session:
            profile = await repo.get_profile(session, callback.message.chat.id)
            facts = await repo.list_active_facts(session, callback.message.chat.id)
            await session.commit()
        text = _profile_text(profile, facts)
        await callback.message.edit_text(text, reply_markup=_back_keyboard())
        await callback.answer()

    @router.callback_query(F.data == "settings:clear")
    async def clear_memory(callback: CallbackQuery) -> None:
        await callback.message.edit_text(
            "⚠️ Удалить сохранённую память?\n\nЭто деактивирует сохранённые факты и удалит сводки прошлых разговоров. Профиль анкеты останется.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Да, очистить", callback_data="settings:clear_confirm")],
                [InlineKeyboardButton(text="← Назад", callback_data="settings:open")],
            ]),
        )
        await callback.answer()

    @router.callback_query(F.data == "settings:clear_confirm")
    async def clear_memory_confirm(callback: CallbackQuery) -> None:
        async with session_factory() as session:
            count = await repo.clear_memory(session, callback.message.chat.id)
            await session.commit()
        await _edit_settings(callback, session_factory)
        await callback.answer(f"Очищено фактов: {count}.")

    @router.callback_query(F.data == "settings:privacy")
    async def privacy(callback: CallbackQuery) -> None:
        await callback.message.edit_text(
            "🔐 Твои данные — под твоим контролем\n\n"
            "BUD использует информацию о тебе для персонализации и запоминания важных деталей.\n\n"
            "Ты можешь в любой момент посмотреть, изменить или удалить сохранённую информацию.\n\n"
            "Если отключить персональную память, BUD продолжит работать как обычный AI-помощник: профиль анкеты сохранится, но долгосрочная память не будет использоваться или пополняться.",
            reply_markup=_back_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "settings:generations")
    async def generations(callback: CallbackQuery) -> None:
        async with session_factory() as session:
            balance = await repo.get_generation_balance(session, callback.message.chat.id)
            await session.commit()
        await callback.message.edit_text(
            "🎨 Генерации\n\n"
            f"Бесплатных осталось: {balance.free_remaining}\n"
            f"Купленных осталось: {balance.purchased_remaining}\n\n"
            "После бесплатных генераций можно покупать пакеты.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎨 10 генераций — 50 ⭐", callback_data="pay:gen10")],
                [InlineKeyboardButton(text="🔥 25 генераций — 100 ⭐", callback_data="pay:gen25")],
                [InlineKeyboardButton(text="🚀 60 генераций — 200 ⭐", callback_data="pay:gen60")],
                [InlineKeyboardButton(text="← Назад", callback_data="settings:open")],
            ]),
        )
        await callback.answer()

    return router


async def _send_settings(message: Message, session_factory: async_sessionmaker[AsyncSession]) -> None:
    text, keyboard = await _settings_view(session_factory, message.chat.id)
    await message.answer(text, reply_markup=keyboard)


async def _edit_settings(callback: CallbackQuery, session_factory: async_sessionmaker[AsyncSession]) -> None:
    text, keyboard = await _settings_view(session_factory, callback.message.chat.id)
    await callback.message.edit_text(text, reply_markup=keyboard)


async def _settings_view(session_factory: async_sessionmaker[AsyncSession], chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with session_factory() as session:
        profile = await repo.get_profile(session, chat_id)
        access = await repo.get_memory_access(session, chat_id)
        balance = await repo.get_generation_balance(session, chat_id)
        await session.commit()
    memory_state = "🟢 включена" if profile.memory_enabled else "🔴 выключена"
    if profile.memory_enabled:
        memory_state += ""
    text = (
        "⚙️ Настройки BUD\n\n"
        f"🧠 Память: {memory_state}\n"
        f"🎨 Генерации: {balance.free_remaining + balance.purchased_remaining} доступно\n\n"
        "Выбери раздел:"
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🧠 Память — {memory_state}", callback_data="settings:memory")],
        [InlineKeyboardButton(text="📋 Что ты обо мне знаешь?", callback_data="settings:profile")],
        [InlineKeyboardButton(text="🎨 Генерации", callback_data="settings:generations")],
        [InlineKeyboardButton(text="🔐 Конфиденциальность", callback_data="settings:privacy")],
    ])


async def _edit_memory(callback: CallbackQuery, session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        profile = await repo.get_profile(session, callback.message.chat.id)
        access = await repo.get_memory_access(session, callback.message.chat.id)
        await repo.freeze_expired_memory(session, callback.message.chat.id)
        await session.commit()
    now = datetime.now(timezone.utc)
    if not profile.memory_enabled:
        status = "🔴 Память отключена"
        detail = "Включи её, чтобы BUD снова использовал и сохранял долгосрочные факты."
    elif access.paid_ends_at and now < access.paid_ends_at:
        status = "🟢 Память активна"
        detail = f"Доступ до {access.paid_ends_at.astimezone().strftime('%d.%m.%Y')}"
    elif now < access.trial_ends_at:
        status = "🟢 Бесплатный период"
        detail = f"Полная память до {access.trial_ends_at.astimezone().strftime('%d.%m.%Y %H:%M')}"
    else:
        status = "🧊 Память заморожена"
        detail = "Сохранённое не удалено. Новые факты не записываются до продления."
    await callback.message.edit_text(
        "🧠 Память BUD\n\n"
        f"{status}\n{detail}\n\n"
        "Купи 1 месяц памяти — получишь второй месяц в подарок.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Включить" if not profile.memory_enabled else "🔴 Выключить", callback_data="settings:memory_toggle")],
            [InlineKeyboardButton(text="💳 Купить 1+1 месяц", callback_data="pay:memory")],
            [InlineKeyboardButton(text="📋 Посмотреть память", callback_data="settings:profile")],
            [InlineKeyboardButton(text="🗑 Очистить память", callback_data="settings:clear")],
            [InlineKeyboardButton(text="← Назад", callback_data="settings:open")],
        ]),
    )


def _profile_text(profile, facts) -> str:
    lines = ["📋 Что BUD знает о тебе", ""]
    if profile.about:
        lines.extend(["✍️ О себе:", profile.about, ""])
    preferences = profile.preferences or {}
    labels = {
        "communication": "Общение",
        "answer_style": "Ответы",
        "interests": "Интересы",
        "help_with": "Помощь",
        "correction_style": "Если ты ошибаешься",
        "remember": "Что запоминать",
    }
    for key, value in preferences.items():
        if value:
            value_text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
            lines.append(f"• {labels.get(key, key)}: {value_text}")
    if facts:
        lines.append("")
        lines.append("🧠 Долгосрочная память:")
        lines.extend(f"• {fact.content}" for fact in facts[:30])
    if not profile.about and not preferences and not facts:
        lines.append("Пока почти ничего. Рассказывай о себе в обычном чате — важное BUD будет запоминать при активной памяти.")
    return "\n".join(lines)


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← Настройки", callback_data="settings:open")],
    ])
