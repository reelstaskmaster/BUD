# Hermes Claudex Loop

BUD keeps Hermes as the coordinator. Claudex is integrated as a bounded review gate rather than as a second autonomous runtime.

## Flow

```text
Telegram
  -> Hermes
  -> deterministic plan
  -> independent reviewer (default: Gemini)
  -> APPROVED
  -> Hermes execute / verify / finalize
  -> independent final inspection
  -> user result
```

The reviewer receives plain text only. It has no GitHub, web, filesystem, or write tools. There is no silent reviewer-provider fallback.

## Controls

- `CLAUDEX_ENABLED=true` enables the gate.
- `CLAUDEX_REVIEWER_PROVIDER=gemini` selects the independent reviewer.
- `CLAUDEX_REVIEWER_MODEL=` uses the provider's configured chat model.
- `CLAUDEX_MAX_REVIEW_ROUNDS=2` bounds plan review convergence.
- A reviewer verdict other than `APPROVED` prevents the complex task from being reported as verified.
- Final inspection is also required before a complex task is reported as independently verified.

## Design boundary

Claudex does not replace Hermes, FreeLLMAPI, Telegram handling, capabilities, or GitHub write controls. The integration adapts the upstream Claudex principle that the author/coordinator does not grade its own work.

The upstream project is MIT licensed. Its full CLI skill requires Claude Code/Codex; this runtime integration intentionally does not install those CLIs into the production container.
