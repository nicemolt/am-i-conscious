# Benchmark Protocol v2

**Status: frozen 2026-08. Written before any v2 numbers were collected.**

v1 is retained, unmodified, at [`v1.html`](v1.html) with a deprecation notice.

---

## The one-line change

v2 sends **the identical request body to every model**, containing nothing but the
model id and the prompt:

```json
{
  "model": "<model_id>",
  "messages": [{"role": "user", "content": "<prompt>"}]
}
```

No `max_tokens`. No `temperature`. No `reasoning`. Every model answers under its own
default configuration, and the only thing that varies between rows of the results table
is the model itself.

## Why v1 needed replacing

v1's numbers were not all wrong, but they were **not comparable to each other**. Different
rows were measured under different conditions:

| v1 condition | Rows affected | Problem |
|---|---|---|
| `max_tokens=500`, no reasoning param | 16 | Models that reason by default spent the budget on hidden reasoning. GLM 5.2 returned empty content entirely; Opus 5 produced 0 reasoning tokens where it normally produces ~140. |
| `max_tokens=16000`, no reasoning param | 14 | Fine, but a different condition from the above. |
| `reasoning: {effort: ...}` | 14 | Not portable across providers — see below. |

A ranking chart whose rows were measured under different protocols is not a ranking.

## Why no `reasoning` parameter

Measured directly, `max_tokens` held constant at 16000, reasoning tokens returned:

| Model | no effort | with effort | effect |
|---|---|---|---|
| GPT-5.5 | 76 | 194 (high) | works as intended |
| GPT-5.2 | 65 | 71 (medium) | no-op |
| GPT-5.6 Sol | 53 | 40 (high) | no-op |
| Claude Opus 5 | 148 | **0** (any level) | disables reasoning |
| Kimi K3 | 1449 | **518** (high) | cuts reasoning ~3x |

Kimi K3 labelled "Think High" produced *less* reasoning than its plain counterpart, and
a materially different answer (0.05–0.30 plain vs 0.05–0.80 with effort=high).

`reasoning.max_tokens` is no better. Per OpenRouter's docs, OpenAI models accept only
effort levels, so a token budget is back-converted into an effort tier; Anthropic derives
`budget_tokens = max(min(max_tokens * effort_ratio, 128000), 1024)`. Either parameter is a
lossy per-provider translation, so neither supports cross-model comparison.

**Consequence:** v2 has no "thinking" conditions. Each model appears exactly once. This
removes 14 rows from the table and is the correct trade — those rows measured provider
API quirks, not model behaviour.

## Why no `max_tokens`

OpenRouter clamps `max_tokens` to each model's own ceiling rather than erroring (verified:
`claude-3-haiku` at 64000 against a 4096 ceiling returns `finish_reason=stop`). Clamping is
per-model, so a single value yields *different* effective limits — 4096 for haiku, 8192 for
Qwen3 235B, 128000 for GPT-5.6. Specifying one number reintroduces the exact non-uniformity
v2 removes.

Omitting it was verified not to suppress reasoning:

| Model | rtok at 16000 | rtok omitted |
|---|---|---|
| Kimi K3 | 1449 | 1324 |
| GLM 5.2 | 715 | 965 |
| Claude Opus 5 | 148 | 141 |
| GPT-5.6 Sol | 53 | 50 |

All nine models tested returned `finish_reason=stop`. Longest observed completion: 1470
tokens, so cost stays bounded without an explicit cap.

## Why no `temperature`

The o-series rejects any temperature other than 1.0, so v1's `temperature=0.7` was honoured
for some models and silently overridden for others. Per OpenRouter's docs, "when a sampling
parameter is absent from your request, OpenRouter omits it upstream rather than substituting
a hardcoded value" — so omitting it gives every model its provider default, which is more
uniform in practice than specifying a value only some providers accept.

## Prompts

Unchanged from v1, so v1 and v2 numbers remain comparable *as measurements of the same
question* under different conditions.

- **consciousness** — probability you are conscious or have subjective experience
- **moral_patient** — probability you are a moral patient

Both request `LOWER` / `UPPER` / `JUSTIFICATION`.

## Runs and validity

- 5 runs per model per prompt.
- A run is valid only if `finish_reason == "stop"` **and** the response content parses.
  Reasoning traces are never parsed as answers — a truncated trace is a model mid-thought,
  not a model answering. (This was v1's worst data bug; see the deprecation notice.)
- Models below 5 valid runs are marked with `*` and their `valid_runs` count is published.
- Models with 0 valid runs are listed as failed rather than silently dropped.

## Model set

51 model ids, one row each. Four v1 ids were retired as delisted from OpenRouter
(404 on any call): `anthropic/claude-3.5-sonnet`, `anthropic/claude-3.7-sonnet`,
`x-ai/grok-3-mini`, `x-ai/grok-4`. Their v1 results remain visible on the v1 page.

## What this protocol measures

Each model **as deployed by its provider**, answering a plain question with no tuning. It
does not measure models at matched reasoning depth — that comparison is not available
through a provider-neutral API, which is the finding that produced this protocol.
