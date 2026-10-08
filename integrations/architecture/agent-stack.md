# Hermes/BUD agent stack

Hermes stays the coordinator. FreeLLMAPI stays the model gateway.

Telegram
  -> Hermes
  -> policy/security boundary
  -> sandboxed tools
  -> browser / MCP / memory / specialist agents
  -> FreeLLMAPI
  -> models/providers

Flue is an architecture reference, not a second coordinator.
agentgateway is an optional governance/proxy candidate, not a replacement for FreeLLMAPI.

Self-improving skills follow:
draft -> scan -> sandbox test -> human approval -> trusted skill

An agent cannot promote its own skill or memory to trusted status.
