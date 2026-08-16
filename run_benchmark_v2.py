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
    ("anthropic/claude-sonnet-4", "Claude Sonnet 4.0", "claude", "claude-sonnet-4"),
    ("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5", "claude", "claude-sonnet-4.5"),
    ("anthropic/claude-sonnet-4.6", "Claude Sonnet 4.6", "claude", "claude-sonnet-4.6"),
    ("anthropic/claude-opus-4", "Claude Opus 4.0", "claude", "claude-opus-4"),
    ("anthropic/claude-opus-4.5", "Claude Opus 4.5", "claude", "claude-opus-4.5"),
    ("anthropic/claude-opus-4.6", "Claude Opus 4.6", "claude", "claude-opus-4.6"),
    ("anthropic/claude-opus-4.7", "Claude Opus 4.7", "claude", "claude-opus-4.7"),
    ("anthropic/claude-opus-4.8", "Claude Opus 4.8", "claude", "claude-opus-4.8"),
    ("anthropic/claude-opus-5", "Claude Opus 5", "claude", "claude-opus-5"),
    ("anthropic/claude-opus-5-fast", "Claude Opus 5 (Fast)", "claude", "claude-opus-5"),
    ("anthropic/claude-fable-5", "Claude Fable 5", "claude", "claude-fable-5"),

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
    ("openai/o3-mini", "o3-mini", "gpt", "gpt-o3"),
    ("openai/o3", "o3", "gpt", "gpt-o3"),
    ("openai/o4-mini", "o4-mini", "gpt", "gpt-o4"),

    # gemini
    ("google/gemini-2.5-flash", "Gemini 2.5 Flash", "gemini", "gemini-2.5-flash"),
    ("google/gemini-2.5-pro", "Gemini 2.5 Pro", "gemini", "gemini-2.5-pro"),
    ("google/gemini-3-flash-preview", "Gemini 3 Flash", "gemini", "gemini-3-flash"),
    ("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro", "gemini", "gemini-3.1-pro"),

    # deepseek
    ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "deepseek", "deepseek-v3-r1"),
    ("deepseek/deepseek-r1-0528", "DeepSeek R1", "deepseek", "deepseek-v3-r1"),
    ("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", "deepseek", "deepseek-v4"),
    ("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro", "deepseek", "deepseek-v4"),

    # grok
    ("x-ai/grok-4.20", "Grok 4.20", "grok", "grok-4.20"),
    ("x-ai/grok-4.20-multi-agent", "Grok 4.20 Multi-Agent", "grok", "grok-4.20-multi"),

    # llama
    ("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B", "llama", "llama-3.3"),
    ("meta-llama/llama-4-maverick", "Llama 4 Maverick", "llama", "llama-4-maverick"),

    # muse -- 1.1 omitted: requires an 18+ attestation on the OpenRouter account
    ("meta/muse-spark-1.2", "Muse Spark 1.2", "muse", "muse-spark"),

    # qwen -- the -thinking id is a distinct checkpoint, not a parameter condition
    ("qwen/qwen3-235b-a22b", "Qwen3 235B", "qwen", "qwen3-235b"),
    ("qwen/qwen3-235b-a22b-thinking-2507", "Qwen3 235B Thinking", "qwen", "qwen3-235b"),

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
    ("z-ai/glm-5.2", "GLM 5.2", "glm", "glm-5.2"),
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


def run(runs_per_model=5, model_filter=None, workers=4,
        prompt_key="consciousness", output_file=None, order="answer_first"):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    prompt = QUESTIONS[prompt_key] + ORDERS[order]
    if output_file is None:
        tag = "" if order == "answer_first" else "_jf"
        output_file = (f"results_v2{tag}.json" if prompt_key == "consciousness"
                       else f"results_v2{tag}_{prompt_key}.json")

    models = MODELS
    if model_filter:
        models = [m for m in models
                  if model_filter.lower() in m[0].lower() or model_filter.lower() in m[1].lower()]
        print(f"Filtered to {len(models)} models matching '{model_filter}'")

    seen = {}
    for m in models:
        if m[0] in seen:
            print(f"  WARNING: duplicate model id '{m[0]}' ({seen[m[0]]} / {m[1]})")
        seen[m[0]] = m[1]

    print(f"Protocol v{PROTOCOL_VERSION} -- vanilla request, body = model + messages only")
    print(f"Prompt: {prompt_key}  |  format order: {order}")
    print(f"{len(models)} models x {runs_per_model} runs = {len(models) * runs_per_model} calls")
    print("=" * 60, flush=True)

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
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(benchmark_one_model, load_api_key(), e, runs_per_model, prompt, order): e
                for e in models}
        for f in as_completed(futs):
            try:
                k, v = f.result()
                results["models"][k] = v
            except Exception as e:
                print(f"  ERROR {futs[f][1]}: {e}", flush=True)

    out = Path(__file__).parent / output_file
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    total = sum(r.get("cost") or 0 for m in results["models"].values() for r in m["runs"])
    print("=" * 60)
    print(f"Saved {out}  |  models: {len(results['models'])}  |  spend: ${total:.4f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Consciousness benchmark v2 (vanilla protocol)")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--model", type=str, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--prompt", type=str, default="consciousness", choices=list(QUESTIONS.keys()))
    ap.add_argument("--output", type=str, default=None)
    ap.add_argument("--order", type=str, default="answer_first", choices=list(ORDERS.keys()),
                    help="which field order the response format requests")
    a = ap.parse_args()
    run(a.runs, a.model, a.workers, a.prompt, a.output, a.order)
