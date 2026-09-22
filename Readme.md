Как запустить:

1. Скопируй `.env.example` в `.env` и пропиши `TELEGRAM_BOT_TOKEN` и `OPENAI_API_KEY`
2. Сгенерируй `FREELLMAPI_ENCRYPTION_KEY` (64 hex-символа) и добавь его в `.env`
3. `docker compose up -d --build`
4. Открой `http://localhost:3001`, добавь ключи провайдеров в FreeLLMAPI и создай unified API key. Вставь его как `FREELLMAPI_API_KEY` в `.env`.
5. Перезапусти BUD: `docker compose up -d --build bot`

Миграции применятся сами при старте контейнера бота.


## FreeLLMAPI fallback

BUD can optionally route chat requests through a local FreeLLMAPI instance. Set FREELLMAPI_API_KEY, FREELLMAPI_BASE_URL, and keep freellmapi in AI_CHAIN. With FREELLMAPI_CHAT_MODEL=auto, the router chooses an available model.

The BUD integration uses FreeLLMAPI for chat/tool calls only. Embeddings, transcription, and image generation remain on their existing providers.

FreeLLMAPI runs separately from BUD. Its official Docker image is ghcr.io/tashfeenahmed/freellmapi:latest; after startup, add provider keys in its dashboard and copy the unified API key into BUD. The project documents an OpenAI-compatible /v1 API and automatic provider failover.

FreeLLMAPI is intended for personal experimentation rather than production inference, so BUD retains its existing OpenRouter/OpenAI fallbacks.
