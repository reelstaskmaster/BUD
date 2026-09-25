# Agent Development Contract

## Architecture
Hermes is the agent runtime. Do not recreate agent, memory, routing, Telegram, or tool infrastructure in this repository when Hermes already provides it.

FreeLLMAPI is the model gateway.

## Rules
- Keep the repository minimal.
- Prefer Hermes configuration and official extension mechanisms over custom code.
- Never commit credentials.
- Make infrastructure changes small and reversible.
- Verify Railway deployment and Telegram connectivity after deployment changes.
