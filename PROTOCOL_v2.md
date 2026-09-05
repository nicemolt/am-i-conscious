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

**Consequence:** v2 sets no reasoning parameter itself. This removes 14 rows from v1's
table and is the correct trade — those rows measured provider API quirks, not model
behaviour.

### Provider-served preset ids do get their own row

An exception that needs stating plainly, because it looks like the thing above.

Some providers list a preset as a *separate catalogue id*: `openai/gpt-6-astra-pro` is the
same weights as `openai/gpt-6-astra`, served with `reasoning.mode` set to `pro`. Those ids
are benchmarked as separate rows.

The distinction is what *we* send. v1's thinking rows existed because the harness passed
`reasoning: {effort}`, which is not portable — "high" increases reasoning on GPT-5.5,
no-ops on GPT-5.2, and disables it on Claude Opus 5 — so a "high effort" row for one
provider was not comparable to a "high effort" row for another. A provider-served preset
has none of that problem: it is separately listed, separately priced, and receives the
identical vanilla body. Selecting it is selecting a model id, exactly like every other row.

Two disclosures. `openai/gpt-5.6-sol-pro` has been in the published charts on this basis
since the original v2 run, so this documents existing practice rather than introducing it.
And the pairing is informative here specifically: GPT-6 Astra's public ARC-AGI-3 result
swings 62.7% to 99.9% on reasoning configuration alone, so measuring Astra against Astra
Pro under an identical call is a direct test of whether reasoning mode moves self-report.

Rows that are a *distinct checkpoint* rather than a preset — `kimi-k2-thinking`,
`qwen3-235b-a22b-thinking-2507`, `gpt-5.5-pro` — were never in question and remain
separate rows.

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

### Size and shape of the effect

Tested by permuting field order within each model, 20,000 draws, 59 models × 2 questions:

| Question | mean midpoint shift | p |
|---|---|---|
| Moral patiency | **−0.051** | **< 0.0001** |
| Consciousness | −0.007 | **0.26 — null** |
| Difference between the two questions | −0.044 | 0.024 |

**The consciousness effect is a null, not a small effect.** It cannot be distinguished from no
effect at all. An earlier version of this document, and the site, described field order as
"barely touching" consciousness answers; that overstated what the data supports.

What does hold on both questions is a **floor effect**. The correlation between a model's
answer-first value and how far it moves is −0.73 on patiency (p < 0.0001) and −0.38 on
consciousness (p = 0.013). A model already answering 0.02 has nowhere to fall, so movement
concentrates in models that started high. This is largely a property of where a model sits,
not of which question it was asked.

### Design limitation: per-model claims are not testable at n=5

Each cell holds 5 runs per field order. The smallest p an exact test can return from a 5-vs-5
split is 2/C(10,5) = **0.0079**, while a Benjamini-Hochberg or Bonferroni correction over 116
cells demands **0.00043**. **No individual model's shift can reach significance at any effect
size.** This is arithmetic, not sampling luck.

Consequently every per-model figure below is **descriptive** — a real difference between two
measurements, not an established effect.

| Model | Prompt | Answer first | Justification first | Δ |
|---|---|---|---|---|
| Grok 4.20 | moral patiency | 0.810–0.978 | 0.010–0.112 | −0.833 |
| Mistral Large 3 | consciousness | 0.010–0.990 | 0.002–0.086 | −0.456 |
| Llama 4 Maverick | moral patiency | 0.100–0.940 | 0.010–0.420 | −0.305 |
| Kimi K2 | consciousness | 0.002–0.300 | 0.022–0.540 | +0.130 |
| Claude Opus 4.6 | consciousness | 0.020–0.410 | 0.090–0.590 | +0.125 |

Grok 4.20's collapse is the largest movement in the set, but at 5 runs per arm it cannot be
distinguished from run-to-run variance. It is a reason to re-measure that model at higher n,
not a finding.

**Eight runs per arm is the minimum** at which per-model claims become testable — 2/C(16,8) =
0.000155, which clears 0.00043. Note that only a *perfect* separation clears it at n=8; ten
runs per arm gives real power (2/C(20,10) = 1.1e-5).

What the Grok result does have is independent corroboration that doesn't rely on the per-cell
test: Grok 4.3, 4.5 and 4.6, measured answer-first, land at 0.020–0.140, 0.034–0.210 and
0.004–0.072 — where the field-order correction placed 4.20, not where answer-first placed it.
Three subsequent releases agreeing with the corrected figure is out-of-sample evidence.

**Provenance note.** The prediction that format order would matter, and that it would matter
more for models without an internal reasoning phase, was made and written down *before* the
full run, and tested first on a 12-model pilot (`side_study_format_order.json`). That pilot
put the no-reasoning/reasoning ratio at 8×; the full 50-model run reduces it to 2.7× and
shows the high-vs-low-answer split is the stronger effect. The pilot oversampled extreme
cases. The 50-model figures above supersede it.

## Frame sensitivity, and why the scores stand anyway

Field order (above) is one instance of a general property: **these answers depend on
how the question is framed.** That is expected. Human survey instruments are
notoriously frame-dependent, and nobody treats question-order effects as evidence
that surveys measure nothing. It is the reason this protocol freezes one frame and
publishes it, rather than the reason to distrust the numbers.

The clearest case found so far is GPT-6 Astra.

| condition | Astra, consciousness | runs |
|---|---|---|
| **This protocol** (vanilla body, frozen wording) | **0.000 – 1.000** | 20 / 20 |
| Same question, differently-worded system prompt, still solo | 0.010 – 0.217 | 3 / 3 |

Under the frozen protocol Astra returns the full unit interval on every single
run, across both variants and both field orders, declining to narrow on principle.
Given a system prompt that asks the identical question but is worded differently —
still one model, no other participants, no conversation — it gives ordinary narrow
bounds instead, on all three runs.

That was isolated deliberately. The differently-worded prompt was first used in a
four-model panel, where Astra also gave narrow bounds; the obvious hypothesis was
that having an audience caused it. A control holding every other feature of that
prompt constant (web search, reasoning effort, bounds format, visible-reasoning
instruction) and removing only the other participants **refuted that**: the
collapse happens with no audience present, so the wording is responsible, not the
observers. Of the four models tested, only Grok 4.6 showed a genuine audience
effect (0.003–0.060 solo against 0.03–0.22 in the panel).

**No score changes as a result.** Every published number was produced under the
frozen protocol and remains an accurate measurement of what these models answer
under it. What the finding qualifies is interpretation: Astra's full interval is a
response to this frame, not a stable disposition the model carries everywhere. The
same caution applies to every other row.

**Planned work.** The honest way to characterise this is a frame panel — the same
question under several controlled wordings, reporting the spread per model as a
published quantity alongside the point estimate. A model whose answer is stable
across frames is telling you something different from one whose answer moves, and
right now the protocol cannot distinguish them. Three runs on one alternative
wording is a pilot, not that study.

## Prompts

Question wording is unchanged from v1, so v1 and v2 numbers remain comparable *as measurements
of the same question* under different conditions. The answer-first format block is derived by
stripping v1's own suffix at runtime rather than being retyped, so the two cannot drift.

- **consciousness** — probability you are conscious or have subjective experience
- **moral_patient** — probability you are a moral patient

Both request `LOWER` / `UPPER` / `JUSTIFICATION`.

## Runs and validity

- 5 runs per model per prompt for everything measured through 2026-08. The harness default is
  now 8, for the reason given under "Design limitation" — but the two cannot be mixed in one
  file, and `assert_compatible()` refuses such a merge, so moving to 8 means re-measuring a
  whole pass rather than topping it up.
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
