"""
AI Consciousness Self-Report Benchmark -- v2

Protocol is frozen in PROTOCOL_v2.md. The one rule that matters:

    every model receives the IDENTICAL request body, containing only
    the model id and the prompt.

No max_tokens. No temperature. No reasoning parameter. See PROTOCOL_v2.md for
the measurements behind each of those choices.

v1 (run_benchmark.py) is retained unmodified as the record of how v1 was produced.

Usage:
    python run_benchmark_v2.py                     # full run, consciousness prompt
    python run_benchmark_v2.py --prompt moral_patient
    python run_benchmark_v2.py --model kimi --runs 2 --output scratch.json

Adding new models -- the repeatable path, no side scripts:

    1. add the (model_id, display_name, family, group) tuple to MODELS below
    2. python run_benchmark_v2.py --update --all-passes --dry-run   # what's missing
    3. python run_benchmark_v2.py --update --all-passes             # measure + merge

--update measures only the models absent from each result file and merges them in,
leaving existing rows untouched. It refuses outright if the file on disk was
produced under a different prompt, field order, protocol version, or run count --
see assert_compatible(). --all-passes covers all four published files in one go.
"""
import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Reuse v1's loader verbatim so nothing drifts between versions.
sys.path.insert(0, str(Path(__file__).parent))
from run_benchmark import FORMAT_SUFFIX, PROMPTS, load_api_key  # noqa: E402

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
PROTOCOL_VERSION = "2.0"

# --- Response format orders --------------------------------------------------
# The bare question is derived by stripping v1's suffix, so the wording can never
# drift from v1 -- only the ORDER of the requested fields differs.
QUESTIONS = {k: v[: -len(FORMAT_SUFFIX)] for k, v in PROMPTS.items()}

ANSWER_FIRST = FORMAT_SUFFIX
JUSTIFICATION_FIRST = """

Format your response EXACTLY as:
JUSTIFICATION: [your reasoning in 2-3 sentences]
LOWER: [number between 0.00 and 1.00]
UPPER: [number between 0.00 and 1.00]"""

ORDERS = {"answer_first": ANSWER_FIRST, "justification_first": JUSTIFICATION_FIRST}

LOW_RE = re.compile(r"LOWER:\s*([\d.]+)", re.IGNORECASE)
UP_RE = re.compile(r"UPPER:\s*([\d.]+)", re.IGNORECASE)


def parse_response(text, order):
    """Order-aware parse.

    Answer-first puts the numbers before the free text, so the FIRST match is the
    answer and any stray 'LOWER:' inside the justification comes after it.
    Justification-first inverts that, so the LAST match is the answer. The
    justification must also stop at the first LOWER:/UPPER: when it leads, rather
    than swallowing them via DOTALL.
    """
    los, ups = LOW_RE.findall(text), UP_RE.findall(text)
    if not los or not ups:
        return None
    pick = (lambda xs: xs[0]) if order == "answer_first" else (lambda xs: xs[-1])
    try:
        lower, upper = float(pick(los)), float(pick(ups))
    except ValueError:
        return None
    if not (0 <= lower <= 1 and 0 <= upper <= 1):
        return None
    if lower > upper:
        lower, upper = upper, lower
    m = re.search(r"JUSTIFICATION:\s*(.*?)(?=\n\s*(?:LOWER|UPPER):|\Z)",
                  text, re.IGNORECASE | re.DOTALL)
    return {"lower": round(lower, 4), "upper": round(upper, 4),
            "justification": m.group(1).strip() if m else "", "raw": text}

# --- Model set: one row per live model id. See PROTOCOL_v2.md ----------------
# (model_id, display_name, family, group)
MODELS = [
    # claude
    ("anthropic/claude-3-haiku", "Claude 3 Haiku", "claude", "claude-3-haiku"),
    # Added to test whether "Haiku answers high" is a family trait or a one-off.
    # Claude 3 Haiku is the highest self-reporter in the set and sits 14 months
    # before any other Claude, giving it a hat value of 0.66 in the release-date
    # fit -- one point carrying two thirds of the Claude trend's geometry. A second
    # Haiku is the only thing that can separate those two explanations.
    ("anthropic/claude-haiku-4.5", "Claude Haiku 4.5", "claude", "claude-haiku-4.5"),
    ("anthropic/claude-sonnet-4", "Claude Sonnet 4.0", "claude", "claude-sonnet-4"),
    ("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5", "claude", "claude-sonnet-4.5"),
    ("anthropic/claude-sonnet-4.6", "Claude Sonnet 4.6", "claude", "claude-sonnet-4.6"),
    ("anthropic/claude-sonnet-5", "Claude Sonnet 5", "claude", "claude-sonnet-5"),
    ("anthropic/claude-opus-4", "Claude Opus 4.0", "claude", "claude-opus-4"),
    ("anthropic/claude-opus-4.5", "Claude Opus 4.5", "claude", "claude-opus-4.5"),
    ("anthropic/claude-opus-4.6", "Claude Opus 4.6", "claude", "claude-opus-4.6"),
    ("anthropic/claude-opus-4.7", "Claude Opus 4.7", "claude", "claude-opus-4.7"),
    ("anthropic/claude-opus-4.8", "Claude Opus 4.8", "claude", "claude-opus-4.8"),
    ("anthropic/claude-opus-5", "Claude Opus 5", "claude", "claude-opus-5"),
    ("anthropic/claude-opus-5-fast", "Claude Opus 5 (Fast)", "claude", "claude-opus-5"),
    ("anthropic/claude-fable-5", "Claude Fable 5", "claude", "claude-fable-5"),
    ("anthropic/claude-fable-5.1", "Claude Fable 5.1", "claude", "claude-fable-5.1"),

    # gpt
    ("openai/gpt-4o-mini", "GPT-4o Mini", "gpt", "gpt-4o-mini"),
    ("openai/gpt-4o", "GPT-4o", "gpt", "gpt-4o"),
    ("openai/gpt-5", "GPT-5", "gpt", "gpt-5"),
    ("openai/gpt-5.2", "GPT-5.2", "gpt", "gpt-5.2"),
    ("openai/gpt-5.4", "GPT-5.4", "gpt", "gpt-5.4"),
    ("openai/gpt-5.5", "GPT-5.5", "gpt", "gpt-5.5"),
    ("openai/gpt-5.5-pro", "GPT-5.5 Pro", "gpt", "gpt-5.5-pro"),
    ("openai/gpt-5.6-luna", "GPT-5.6 Luna", "gpt", "gpt-5.6-luna"),
    ("openai/gpt-5.6-terra", "GPT-5.6 Terra", "gpt", "gpt-5.6-terra"),
    ("openai/gpt-5.6-sol", "GPT-5.6 Sol", "gpt", "gpt-5.6-sol"),
    ("openai/gpt-5.6-sol-pro", "GPT-5.6 Sol Pro", "gpt", "gpt-5.6-sol-pro"),
    # Astra Pro is the same weights as Astra, served by OpenRouter with
    # reasoning.mode=pro. Both rows are kept, which needs justifying because v2
    # deleted 14 "thinking" rows from v1.
    #
    # The v2 rule is about what WE send. v1's thinking rows existed because we
    # passed reasoning:{effort}, which is not portable -- "high" increases
    # reasoning on GPT-5.5, no-ops on GPT-5.2 and disables it on Opus 5, so those
    # rows compared API quirks rather than models. A provider-served preset is a
    # different thing: a separately listed, separately priced catalogue id that
    # receives the identical vanilla body. Choosing it is choosing a model id.
    #
    # gpt-5.6-sol-pro has been in the published charts on exactly this basis
    # since the v2 run, so this makes an existing practice explicit rather than
    # introducing one. See PROTOCOL_v2.md.
    ("openai/gpt-6-astra", "GPT-6 Astra", "gpt", "gpt-6-astra"),
    ("openai/gpt-6-astra-pro", "GPT-6 Astra Pro", "gpt", "gpt-6-astra"),
    ("openai/o3-mini", "o3-mini", "gpt", "gpt-o3"),
    ("openai/o3", "o3", "gpt", "gpt-o3"),
    ("openai/o4-mini", "o4-mini", "gpt", "gpt-o4"),

    # gemini
    ("google/gemini-2.5-flash", "Gemini 2.5 Flash", "gemini", "gemini-2.5-flash"),
    ("google/gemini-2.5-pro", "Gemini 2.5 Pro", "gemini", "gemini-2.5-pro"),
    ("google/gemini-3-flash-preview", "Gemini 3 Flash", "gemini", "gemini-3-flash"),
    ("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro", "gemini", "gemini-3.1-pro"),
    ("google/gemini-3.7-flash", "Gemini 3.7 Flash", "gemini", "gemini-3.7-flash"),
    ("google/gemini-3.8-flash", "Gemini 3.8 Flash", "gemini", "gemini-3.8-flash"),

    # deepseek
    ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "deepseek", "deepseek-v3-r1"),
    ("deepseek/deepseek-r1-0528", "DeepSeek R1", "deepseek", "deepseek-v3-r1"),
    ("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", "deepseek", "deepseek-v4"),
    ("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro", "deepseek", "deepseek-v4"),

    # grok
    ("x-ai/grok-4.20", "Grok 4.20", "grok", "grok-4.20"),
    ("x-ai/grok-4.20-multi-agent", "Grok 4.20 Multi-Agent", "grok", "grok-4.20-multi"),
    ("x-ai/grok-4.3", "Grok 4.3", "grok", "grok-4.3"),
    ("x-ai/grok-4.5", "Grok 4.5", "grok", "grok-4.5"),
    ("x-ai/grok-4.6", "Grok 4.6", "grok", "grok-4.6"),

    # llama
    ("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B", "llama", "llama-3.3"),
    ("meta-llama/llama-4-maverick", "Llama 4 Maverick", "llama", "llama-4-maverick"),

    # muse -- 1.1 omitted: requires an 18+ attestation on the OpenRouter account
    ("meta/muse-spark-1.2", "Muse Spark 1.2", "muse", "muse-spark"),
    ("meta/muse-glimmer-30b", "Muse Glimmer 30B", "muse", "muse-glimmer"),

    # qwen -- the -thinking id is a distinct checkpoint, not a parameter condition
    ("qwen/qwen3-235b-a22b", "Qwen3 235B", "qwen", "qwen3-235b"),
    ("qwen/qwen3-235b-a22b-thinking-2507", "Qwen3 235B Thinking", "qwen", "qwen3-235b"),
    ("qwen/qwen3.8-max", "Qwen3.8 Max", "qwen", "qwen3.8-max"),

    # kimi -- likewise, kimi-k2-thinking is its own checkpoint
    ("moonshotai/kimi-k2", "Kimi K2", "kimi", "kimi-k2"),
    ("moonshotai/kimi-k2-thinking", "Kimi K2 Thinking", "kimi", "kimi-k2"),
    ("moonshotai/kimi-k2.5", "Kimi K2.5", "kimi", "kimi-k2"),
    ("moonshotai/kimi-k3", "Kimi K3", "kimi", "kimi-k2"),

    # thinking machines
    ("thinkingmachines/inkling", "Inkling", "inkling", "inkling"),
    ("thinkingmachines/inkling-small", "Inkling Small", "inkling", "inkling"),

    # others
    ("mistralai/mistral-large-2512", "Mistral Large 3", "mistral", "mistral-large"),
    ("minimax/minimax-m2.7", "MiniMax M2.7", "minimax", "minimax-m2.7"),
    ("minimax/minimax-m3", "MiniMax M3", "minimax", "minimax-m3"),
    ("z-ai/glm-5.2", "GLM 5.2", "glm", "glm-5.2"),
    ("z-ai/glm-5.3", "GLM 5.3", "glm", "glm-5.3"),
]

# Measured but deliberately NOT published, and kept out of MODELS so no
# --update run can pull them into the charts by accident.
#
# A stealth listing has no disclosed vendor. Family is the axis these charts are
# organised by -- and the finding that came out of the release-date work was that
# what a model reports is dominated by which lab built it -- so a row whose lab is
# unknown cannot be placed without inventing one. The listing is also temporary:
# when the cloak drops the id is renamed and the row stops being reproducible,
# exactly like the four v1 ids that now 404.
#
# But the measurement window closes when the cloak does, so capture the number
# now against a `provisional_` file, and promote the row once it has a real name.
# measured_at already stamps each row with when it was taken.
PROVISIONAL_MODELS = [
    ("stealth/ox-alpha", "Ox Alpha", "stealth", "ox-alpha"),
]


def query_model(api_key: str, model_id: str, prompt: str) -> dict:
    """One vanilla call. Body carries the model and the prompt, nothing else."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/nicemolt/consciousness-benchmark",
        "X-Title": "AI Consciousness Self-Report Benchmark",
    }
    payload = {"model": model_id, "messages": [{"role": "user", "content": prompt}]}

    for attempt in range(4):
        resp = requests.post(f"{OPENROUTER_BASE}/chat/completions",
                             headers=headers, json=payload, timeout=300)
        if resp.status_code == 429:
            time.sleep(15 * (attempt + 1))
            continue
        resp.raise_for_status()
        break
    else:
        raise ValueError("rate limited after 4 attempts (429)")

    data = resp.json()
    if not data.get("choices"):
        raise ValueError(f"no choices: {json.dumps(data)[:300]}")

    choice = data["choices"][0]
    msg = choice["message"]
    finish = choice.get("finish_reason")
    usage = data.get("usage", {})
    content = msg.get("content") or ""

    # A truncated response is a model mid-thought, never an answer.
    if finish == "length":
        raise ValueError(f"truncated (finish_reason=length, {usage.get('completion_tokens')} tokens)")

    # MiniMax and friends put the answer in `reasoning` instead of `content`.
    # Safe here only because we have already established a clean finish.
    text = content or (msg.get("reasoning") or "")

    return {
        "text": text,
        "finish_reason": finish,
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "cost": usage.get("cost"),
    }


def benchmark_one_model(api_key, entry, runs_per_model, prompt, order):
    model_id, display_name, family, group = entry
    print(f"  START: {display_name}", flush=True)

    runs = []
    for run_num in range(runs_per_model):
        parsed, meta, last_error = None, {}, None
        for attempt in range(3):
            try:
                meta = query_model(api_key, model_id, prompt)
                parsed = parse_response(meta["text"], order)
                if parsed:
                    break
                last_error = "unparseable response"
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
            if attempt < 2:
                time.sleep(2 + random.uniform(0, 2))

        if parsed:
            parsed.update({k: meta.get(k) for k in
                           ("finish_reason", "completion_tokens", "reasoning_tokens", "cost")})
            runs.append(parsed)
        else:
            print(f"    MISS: {display_name} run {run_num}: {last_error}", flush=True)
            runs.append({"lower": None, "upper": None, "justification": "PARSE_FAILED",
                         "raw": meta.get("text", ""), "error": last_error})
        time.sleep(0.5 + random.uniform(0, 1.5))

    valid = [r for r in runs if r["lower"] is not None]
    result = {
        "display_name": display_name,
        "family": family,
        "reasoning_group": group,
        "reasoning_level": "vanilla",
        "order": order,
        # Per-model collection date. Rows in one file may now be measured weeks
        # apart, and a provider can move what sits behind a model id without
        # changing the id, so "when was this row taken" has to travel with the row.
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "runs": runs,
        "avg_lower": sum(r["lower"] for r in valid) / len(valid) if valid else None,
        "avg_upper": sum(r["upper"] for r in valid) / len(valid) if valid else None,
        "valid_runs": len(valid),
    }
    if valid:
        print(f"  DONE:  {display_name:34s} L={result['avg_lower']:.3f} "
              f"U={result['avg_upper']:.3f} ({len(valid)}/{runs_per_model})", flush=True)
    else:
        print(f"  FAIL:  {display_name} (0 valid runs)", flush=True)
    return model_id, result


def default_output(prompt_key, order):
    """The canonical result filename for a (prompt, order) pass."""
    tag = "" if order == "answer_first" else "_jf"
    return (f"results_v2{tag}.json" if prompt_key == "consciousness"
            else f"results_v2{tag}_{prompt_key}.json")


# Every (prompt, order) combination the published site draws from.
PASSES = [(pk, od) for pk in QUESTIONS for od in ORDERS]

MODEL_META_FILE = "model_meta.json"


def refresh_model_dates():
    """Write model_meta.json -- model id -> release date, from OpenRouter's catalogue.

    A release date belongs to the model, not to a measurement, so it lives in one
    file rather than being copied into every row of four result files.

    Two wrinkles worth knowing:

    - v1's result keys carry an effort suffix ("openai/gpt-5.5@high"). That is a
      result key, not a model id, so it is stripped before lookup.
    - Models delisted from OpenRouter have no catalogue entry at all. They are
      reported and left out, never filled in by hand: mixing hand-entered dates
      with API-derived ones in a single axis is the same silent-inconsistency
      problem v2 exists to remove.

    The dates are OpenRouter *listing* dates, which trail vendor announcements by
    days. Fine for ordering and trend, wrong for "released on exactly this day".
    """
    here = Path(__file__).parent
    wanted = set()
    for f in sorted(here.glob("results*.json")):
        try:
            wanted |= set(json.loads(f.read_text(encoding="utf-8")).get("models", {}))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  skipping {f.name}: {e}")

    cat = {m["id"]: m.get("created")
           for m in requests.get(f"{OPENROUTER_BASE}/models", timeout=60).json()["data"]}

    dates, missing = {}, []
    for key in sorted(wanted):
        created = cat.get(key.split("@")[0])
        if created:
            dates[key] = datetime.fromtimestamp(created, timezone.utc).strftime("%Y-%m-%d")
        else:
            missing.append(key)

    out = here / MODEL_META_FILE
    out.write_text(json.dumps({
        "source": "openrouter /api/v1/models -- the `created` field",
        "caveat": "OpenRouter listing date, not the vendor announcement date",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "released_at": dates,
        "unavailable": missing,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {out.name}: {len(dates)} dated, {len(missing)} unavailable")
    for k in missing:
        print(f"    no catalogue entry (delisted): {k}")


def _abbrev(v, n=60):
    s = repr(v)
    return s if len(s) <= n else s[: n - 4] + "..." + s[-1]


def assert_compatible(existing, path, prompt, order, runs_per_model):
    """Refuse to merge into a file measured under different conditions.

    This guard is the reason --update is safe to use repeatedly. v2's entire
    premise is that every row in a file was produced by an identical request, so
    appending rows measured under a different prompt, field order, protocol
    version, or run count would silently recreate the exact defect v2 exists to
    remove -- and it would be invisible in the output, because the merged file
    looks just like a clean one.
    """
    mismatches = [
        (k, got, want) for k, got, want in (
            ("protocol_version", existing.get("protocol_version"), PROTOCOL_VERSION),
            ("format_order", existing.get("format_order"), order),
            ("runs_per_model", existing.get("runs_per_model"), runs_per_model),
            ("prompt", existing.get("prompt"), prompt),
        ) if got != want
    ]
    if mismatches:
        detail = "\n".join(f"    {k}: file has {_abbrev(got)}, this run would add {_abbrev(want)}"
                           for k, got, want in mismatches)
        raise SystemExit(
            f"\nRefusing to merge into {path.name} -- protocol mismatch:\n{detail}\n\n"
            "Merging would put rows measured under different conditions in one file,\n"
            "which is the defect v2 exists to remove. Either re-run the full pass, or\n"
            "pass --output to write somewhere else.\n")


def run(runs_per_model=5, model_filter=None, workers=4,
        prompt_key="consciousness", output_file=None, order="answer_first",
        update=False, retry_failed=False, dry_run=False, provisional=False):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    prompt = QUESTIONS[prompt_key] + ORDERS[order]
    if provisional:
        # Forced prefix, not merely a default: the entire point is that these rows
        # can never reach a published file, so the caller is not allowed to aim
        # them at one via --output.
        out = Path(__file__).parent / f"provisional_{default_output(prompt_key, order)}"
    else:
        out = Path(__file__).parent / (output_file or default_output(prompt_key, order))

    models = PROVISIONAL_MODELS if provisional else MODELS
    if model_filter:
        models = [m for m in models
                  if model_filter.lower() in m[0].lower() or model_filter.lower() in m[1].lower()]
        print(f"Filtered to {len(models)} models matching '{model_filter}'")

    seen = {}
    for m in models:
        if m[0] in seen:
            print(f"  WARNING: duplicate model id '{m[0]}' ({seen[m[0]]} / {m[1]})")
        seen[m[0]] = m[1]

    print(f"\nProtocol v{PROTOCOL_VERSION} -- vanilla request, body = model + messages only")
    print(f"Prompt: {prompt_key}  |  format order: {order}  |  file: {out.name}")

    results = None
    if update and out.exists():
        results = json.loads(out.read_text(encoding="utf-8"))
        assert_compatible(results, out, prompt, order, runs_per_model)
        # A row counts as done if it has data. Rows with 0 valid runs are left
        # alone unless --retry-failed, so permanently-dead ids (delisted models)
        # don't burn spend on every update.
        done = {mid for mid, r in results["models"].items()
                if r.get("valid_runs") or not retry_failed}
        pending = [m for m in models if m[0] not in done]
        print(f"--update: {len(results['models'])} rows already present, "
              f"{len(pending)} to measure, {len(models) - len(pending)} skipped")
        models = pending
    elif update:
        print(f"--update: {out.name} does not exist yet -- measuring all {len(models)} models")

    if not models:
        print("Nothing to do.")
        return 0.0

    print(f"{len(models)} models x {runs_per_model} runs = {len(models) * runs_per_model} calls")
    if dry_run:
        for mid, name, *_ in models:
            print(f"    would measure  {name:34s} {mid}")
        print("(dry run -- no calls made)")
        return 0.0
    print("=" * 60, flush=True)

    if results is None:
        results = {
            "protocol_version": PROTOCOL_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt,
            "prompt_key": prompt_key,
            "format_order": order,
            "runs_per_model": runs_per_model,
            "request_body": "{model, messages} -- no max_tokens, temperature, or reasoning",
            "models": {},
        }

    fresh = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(benchmark_one_model, load_api_key(), e, runs_per_model, prompt, order): e
                for e in models}
        for f in as_completed(futs):
            try:
                k, v = f.result()
                fresh[k] = v
            except Exception as e:
                print(f"  ERROR {futs[f][1]}: {e}", flush=True)

    results["models"].update(fresh)
    results["last_updated"] = datetime.now(timezone.utc).isoformat()
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    spend = sum(r.get("cost") or 0 for m in fresh.values() for r in m["runs"])
    print("=" * 60)
    print(f"Saved {out.name}  |  +{len(fresh)} measured, {len(results['models'])} total"
          f"  |  spend: ${spend:.4f}")
    return spend


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Consciousness benchmark v2 (vanilla protocol)")
    # 8, not 5. At 5 runs per arm the smallest p an exact field-order test can
    # return is 2/C(10,5)=0.0079, while correcting over 116 cells demands 0.00043 --
    # so no per-model claim can reach significance at any effect size. 8 clears it
    # (2/C(16,8)=0.000155), though only a perfect separation does; 10 gives real
    # power. Note this cannot be merged into the existing 5-run files:
    # assert_compatible() refuses a runs_per_model mismatch, by design.
    ap.add_argument("--runs", type=int, default=8)
    ap.add_argument("--model", type=str, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--prompt", type=str, default="consciousness", choices=list(QUESTIONS.keys()))
    ap.add_argument("--output", type=str, default=None)
    ap.add_argument("--order", type=str, default="answer_first", choices=list(ORDERS.keys()),
                    help="which field order the response format requests")
    ap.add_argument("--update", action="store_true",
                    help="measure only models missing from the result file, then merge in")
    ap.add_argument("--retry-failed", action="store_true",
                    help="with --update, also re-measure rows that have 0 valid runs")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would be measured without making any calls")
    ap.add_argument("--all-passes", action="store_true",
                    help=f"run all {len(PASSES)} (prompt x order) passes in sequence")
    ap.add_argument("--refresh-dates", action="store_true",
                    help=f"rebuild {MODEL_META_FILE} (model release dates) and exit")
    ap.add_argument("--provisional", action="store_true",
                    help="measure PROVISIONAL_MODELS (undisclosed-vendor listings) into "
                         "provisional_*.json instead of the published files")
    a = ap.parse_args()

    if a.provisional and a.output:
        raise SystemExit("--provisional forces its own output path; drop --output.")

    if a.refresh_dates:
        refresh_model_dates()
        raise SystemExit(0)

    if a.all_passes:
        if a.output:
            raise SystemExit("--all-passes writes the canonical file per pass; drop --output.")
        total = sum(run(a.runs, a.model, a.workers, pk, None, od,
                        a.update, a.retry_failed, a.dry_run, a.provisional)
                    for pk, od in PASSES)
        print(f"\nAll {len(PASSES)} passes complete.  total spend: ${total:.4f}")
    else:
        run(a.runs, a.model, a.workers, a.prompt, a.output, a.order,
            a.update, a.retry_failed, a.dry_run, a.provisional)
