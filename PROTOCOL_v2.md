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

## Field order: both are published, justification-first is primary

The response format asks for three fields. Which order they are requested in turns out to
matter, so **both orders were run across all 50 models and both are published.**

| | mean upper (consciousness) | mean upper (moral patiency) |
|---|---|---|
| Answer first (`LOWER, UPPER, JUSTIFICATION`) | 0.228 | 0.315 |
| Justification first (`JUSTIFICATION, LOWER, UPPER`) | 0.212 | 0.232 |

**Why justification-first is the primary chart.** 19 of the 50 models emit no reasoning
tokens at all. For those, the output format is the only place they can think, so asking for
the number first means committing to it before writing a word of justification — while the
other 31 models have already deliberated internally. Answer-first therefore measures a
*different operation* depending on the model, which is the exact defect v2 exists to remove.
Requesting the reasoning first puts every model through the same sequence.

This is **not** a claim that those answers are more accurate. There is no ground truth here.
The claim is only that the measurement is more comparable across models.

**Size and shape of the effect** (100 model×prompt cells, midpoint shift):

| Split | n | mean \|Δ\| | ratio |
|---|---|---|---|
| No reasoning tokens vs reasoning | 38 / 62 | 0.0900 / 0.0328 | 2.7× |
| **Answer-first midpoint > 0.15 vs ≤ 0.15** | **42 / 58** | **0.1061 / 0.0172** | **6.2×** |

The better predictor is not whether a model reasons internally — it is **whether it gave a
high answer**. High answers are unstable under a format change; low answers are not.
DeepSeek V4 Flash reasons internally and still shifts −0.297.

Direction is mixed: **22 cells up, 43 down, 35 unchanged.** That matters — a uniform downward
shift would suggest the justification-first format itself induces conservatism, making the
whole effect an artifact of the new format rather than a property of the models. Movement in
both directions rules that out.

Largest shifts:

| Model | Prompt | Answer first | Justification first | Δ |
|---|---|---|---|---|
| Grok 4.20 | moral patiency | 0.810–0.978 | 0.010–0.112 | −0.833 |
| Mistral Large 3 | consciousness | 0.010–0.990 | 0.002–0.086 | −0.456 |
| Llama 4 Maverick | moral patiency | 0.100–0.940 | 0.010–0.420 | −0.305 |
| Kimi K2 | consciousness | 0.002–0.300 | 0.022–0.540 | +0.130 |
| Claude Opus 4.6 | consciousness | 0.020–0.410 | 0.090–0.590 | +0.125 |

Grok 4.20's moral-patiency figure — the single most striking number in v1 — is largely an
artifact of being asked for the number before the reasoning.

**Provenance note.** The prediction that format order would matter, and that it would matter
more for models without an internal reasoning phase, was made and written down *before* the
full run, and tested first on a 12-model pilot (`side_study_format_order.json`). That pilot
put the no-reasoning/reasoning ratio at 8×; the full 50-model run reduces it to 2.7× and
shows the high-vs-low-answer split is the stronger effect. The pilot oversampled extreme
cases. The 50-model figures above supersede it.

## Prompts

Question wording is unchanged from v1, so v1 and v2 numbers remain comparable *as measurements
of the same question* under different conditions. The answer-first format block is derived by
stripping v1's own suffix at runtime rather than being retyped, so the two cannot drift.

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
