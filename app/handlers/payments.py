from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import repositories as repo

MEMORY_PRICE_STARS = 100
GENERATION_PACKS = {
    "gen10": (10, 50),
    "gen25": (25, 100),
    "gen60": (60, 200),
}


def build_router(*, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> Router:
    router = Router(name="payments")

    @router.callback_query(F.data == "pay:memory")
    async def buy_memory(callback: CallbackQuery) -> None:
        await callback.message.answer_invoice(
            title="Память BUD 1+1 месяц",
            description="1 месяц памяти оплачиваешь, второй месяц получаешь в подарок.",
            payload="memory_1plus1",
            currency="XTR",
            prices=[LabeledPrice(label="Память BUD 1+1 месяц", amount=settings.memory_price_stars)],
            provider_token="",
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("pay:gen"))
    async def buy_generations(callback: CallbackQuery) -> None:
        key = (callback.data or "").split(":", 1)[1]
        pack = GENERATION_PACKS.get(key)
        if pack is None:
            await callback.answer("Пакет не найден.", show_alert=True)
            return
        amount, stars = pack
        await callback.message.answer_invoice(
            title=f"BUD — {amount} генераций",
            description=f"Пакет из {amount} генераций изображений BUD.",
            payload=f"gen_{amount}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{amount} генераций", amount=stars)],
            provider_token="",
        )
        await callback.answer()

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
        if payment is None:
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
