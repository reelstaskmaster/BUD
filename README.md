# BUD

BUD is now an infrastructure repository for a Hermes Agent deployment on Railway.

## Architecture

Telegram → Hermes → FreeLLMAPI → available model providers

Hermes is the agent runtime. The repository intentionally does not contain a second custom Telegram/LLM agent implementation.

## Railway

The Hermes wrapper lives in `infra/freellmapi-railway/`.
