from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import repositories as repo

GENERATION_PACKS = {
    "gen10": (10, 50),
    "gen25": (25, 100),
    "gen60": (60, 200),
}

TERMS_TEXT = (
    "📄 Условия покупки BUD\n\n"
    "BUD продаёт цифровые услуги: долгосрочную память и генерации изображений. "
    "Оплата внутри Telegram производится в Telegram Stars.\n\n"
    "Память: 1 оплаченный месяц + 1 месяц в подарок. После окончания доступа новые записи памяти прекращаются, а сохранённая память не удаляется автоматически.\n\n"
    "Генерации: после бесплатного лимита доступны платные пакеты. Купленные генерации не являются подпиской.\n\n"
    "Нажимая «Согласен», ты подтверждаешь, что прочитал и принимаешь эти условия."
)
SUPPORT_TEXT = (
    "🆘 Поддержка BUD\n\n"
    "По вопросам оплаты или покупки опиши проблему здесь и, если есть, приложи чек Telegram. "
    "Не отправляй данные банковской карты."
)


def build_router(*, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> Router:
    router = Router(name="payments")

    @router.message(Command("terms"), F.chat.type == "private")
    async def terms(message: Message) -> None:
        await message.answer(TERMS_TEXT)

    @router.message(Command("paysupport"), F.chat.type == "private")
    async def pay_support(message: Message) -> None:
        await message.answer(SUPPORT_TEXT)

    @router.callback_query(F.data == "pay:memory")
    async def buy_memory(callback: CallbackQuery) -> None:
        if not await _terms_accepted(callback, session_factory):
            await _ask_terms(callback)
            return
        await _send_memory_invoice(callback.message, settings)
        await callback.answer()

    @router.callback_query(F.data.startswith("pay:gen"))
    async def buy_generations(callback: CallbackQuery) -> None:
        key = (callback.data or "").split(":", 1)[1]
        pack = GENERATION_PACKS.get(key)
        if pack is None:
            await callback.answer("Пакет не найден.", show_alert=True)
            return
        if not await _terms_accepted(callback, session_factory):
            await _ask_terms(callback)
            return
        await _send_generation_invoice(callback.message, pack)
        await callback.answer()

    @router.callback_query(F.data == "pay:terms_accept")
    async def accept_terms(callback: CallbackQuery) -> None:
        async with session_factory() as session:
            profile = await repo.get_profile(session, callback.message.chat.id)
            profile.terms_accepted = True
            await session.commit()
        await callback.message.edit_text(
            "✅ Условия приняты. Теперь выбери покупку:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧠 Память 1+1 месяц", callback_data="pay:memory")],
                [InlineKeyboardButton(text="🎨 Пакеты генераций", callback_data="settings:generations")],
                [InlineKeyboardButton(text="← Настройки", callback_data="settings:open")],
            ]),
        )
        await callback.answer("Условия приняты.")

    @router.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery) -> None:
        if query.currency != "XTR":
            await query.answer(ok=False, error_message="Этот платёж должен быть в Telegram Stars.")
            return
        if not _valid_payload(query.invoice_payload, query.total_amount, settings):
            await query.answer(ok=False, error_message="Не удалось проверить заказ. Попробуй ещё раз.")
            return
        await query.answer(ok=True)

    @router.message(F.successful_payment)
    async def successful_payment(message: Message) -> None:
        payment = message.successful_payment
        if payment is None or not _valid_payload(payment.invoice_payload, payment.total_amount, settings):
            return
        async with session_factory() as session:
            recorded = await repo.record_payment(
                session,
                chat_id=message.chat.id,
                payload=payment.invoice_payload,
                currency=payment.currency,
                total_amount=payment.total_amount,
                charge_id=payment.telegram_payment_charge_id,
            )
            if recorded is None:
                await session.rollback()
                return
            if payment.invoice_payload == "memory_1plus1":
                await repo.grant_paid_memory(session, message.chat.id)
                text = "✅ Готово. Память BUD продлена на 2 календарных месяца: 1 оплаченный + 1 в подарок."
            else:
                amount = _generation_amount(payment.invoice_payload)
                if amount is None:
                    await session.rollback()
                    return
                await repo.add_purchased_generations(session, message.chat.id, amount)
                text = f"✅ Готово. На баланс добавлено {amount} генераций."
            await session.commit()
        await message.answer(text)

    return router


async def _terms_accepted(callback: CallbackQuery, session_factory: async_sessionmaker[AsyncSession]) -> bool:
    async with session_factory() as session:
        profile = await repo.get_profile(session, callback.message.chat.id)
        accepted = profile.terms_accepted
        await session.commit()
    return accepted


async def _ask_terms(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        TERMS_TEXT,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Согласен и продолжить", callback_data="pay:terms_accept")],
            [InlineKeyboardButton(text="← Назад", callback_data="settings:open")],
        ]),
    )
    await callback.answer("Сначала прими условия покупки.")


async def _send_memory_invoice(message: Message, settings: Settings) -> None:
    await message.answer_invoice(
        title="Память BUD 1+1 месяц",
        description="1 месяц памяти оплачиваешь, второй месяц получаешь в подарок.",
        payload="memory_1plus1",
        currency="XTR",
        prices=[LabeledPrice(label="Память BUD 1+1 месяц", amount=settings.memory_price_stars)],
        provider_token="",
    )


async def _send_generation_invoice(message: Message, pack: tuple[int, int]) -> None:
    amount, stars = pack
    await message.answer_invoice(
        title=f"BUD — {amount} генераций",
        description=f"Пакет из {amount} генераций изображений BUD.",
        payload=f"gen_{amount}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{amount} генераций", amount=stars)],
        provider_token="",
    )


def _generation_amount(payload: str) -> int | None:
    if not payload.startswith("gen_"):
        return None
    try:
        amount = int(payload.removeprefix("gen_"))
    except ValueError:
        return None
    return amount if any(pack[0] == amount for pack in GENERATION_PACKS.values()) else None


def _valid_payload(payload: str, total_amount: int, settings: Settings) -> bool:
    if payload == "memory_1plus1":
        return total_amount == settings.memory_price_stars
    amount = _generation_amount(payload)
    if amount is None:
        return False
    return total_amount == GENERATION_PACKS[f"gen{amount}"][1]
