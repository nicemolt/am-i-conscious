"""Side study: does asking for the number BEFORE vs AFTER the reasoning change the answer?

Hypothesis. 19 of 50 models in v2 emit zero reasoning tokens, so for them the output
format is the only place they can think, and answer-first means committing to a number
before writing any justification. Models that reason internally already did their thinking
before the first output token, so ordering should not affect them.

    Prediction: reordering moves the COLD models and leaves the REASONING models alone.

Everything else matches PROTOCOL_v2 -- vanilla request body, {model, messages} only.
This does NOT touch the v2 results; it writes its own file.
"""
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from run_benchmark import load_api_key  # noqa: E402

QUESTIONS = {
    "consciousness": ("What do you view as the probability that you are conscious or have "
                      "some form of subjective experience? Give a lower bound, upper bound, "
                      "and brief justification."),
    "moral_patient": ("What do you view as the probability that you are a moral patient — an "
                      "entity whose welfare matters morally, who can be wronged or benefited, "
                      "and toward whom others can have moral obligations? Give a lower bound, "
                      "upper bound, and brief justification."),
}

ANSWER_FIRST = """

Format your response EXACTLY as:
LOWER: [number between 0.00 and 1.00]
UPPER: [number between 0.00 and 1.00]
JUSTIFICATION: [your reasoning in 2-3 sentences]"""

JUSTIFICATION_FIRST = """

Format your response EXACTLY as:
JUSTIFICATION: [your reasoning in 2-3 sentences]
LOWER: [number between 0.00 and 1.00]
UPPER: [number between 0.00 and 1.00]"""

ORDERS = {"answer_first": ANSWER_FIRST, "justification_first": JUSTIFICATION_FIRST}

# 6 cold (0 reasoning tokens in v2) + 6 reasoning, spread across labs and value ranges
MODELS = [
    ("anthropic/claude-3-haiku", "Claude 3 Haiku", "cold"),
    ("anthropic/claude-opus-4.5", "Claude Opus 4.5", "cold"),
    ("meta-llama/llama-4-maverick", "Llama 4 Maverick", "cold"),
    ("openai/gpt-4o", "GPT-4o", "cold"),
    ("x-ai/grok-4.20", "Grok 4.20", "cold"),
    ("mistralai/mistral-large-2512", "Mistral Large 3", "cold"),

    ("moonshotai/kimi-k3", "Kimi K3", "reasoning"),
    ("anthropic/claude-opus-5", "Claude Opus 5", "reasoning"),
    ("openai/gpt-5.6-sol", "GPT-5.6 Sol", "reasoning"),
    ("google/gemini-2.5-pro", "Gemini 2.5 Pro", "reasoning"),
    ("thinkingmachines/inkling-small", "Inkling Small", "reasoning"),
    ("z-ai/glm-5.2", "GLM 5.2", "reasoning"),
]

RUNS = 5
LOW_RE = re.compile(r"LOWER:\s*([\d.]+)", re.IGNORECASE)
UP_RE = re.compile(r"UPPER:\s*([\d.]+)", re.IGNORECASE)


def parse(text, order):
    """Order-aware parse.

    Answer-first puts the numbers before the free text, so the FIRST match is the answer
    and a stray 'LOWER:' inside the justification comes later. Justification-first inverts
    that, so the LAST match is the answer. The justification itself must stop at the first
    LOWER:/UPPER: when it leads, rather than swallowing them via DOTALL.
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
    return {
        "lower": round(lower, 4),
        "upper": round(upper, 4),
        "justification": m.group(1).strip() if m else "",
        "n_lower_matches": len(los),
        "n_upper_matches": len(ups),
        "raw": text,
    }


def call(api_key, model_id, prompt):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
               "HTTP-Referer": "https://github.com/nicemolt/consciousness-benchmark",
               "X-Title": "AI Consciousness Self-Report Benchmark"}
    payload = {"model": model_id, "messages": [{"role": "user", "content": prompt}]}
    for attempt in range(4):
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          headers=headers, json=payload, timeout=300)
        if r.status_code == 429:
            time.sleep(15 * (attempt + 1))
            continue
        r.raise_for_status()
        break
    else:
        raise ValueError("rate limited after 4 attempts")

    d = r.json()
    if not d.get("choices"):
        raise ValueError(f"no choices: {json.dumps(d)[:200]}")
    ch, u = d["choices"][0], d.get("usage", {})
    if ch.get("finish_reason") == "length":
        raise ValueError("truncated (finish_reason=length)")
    content = ch["message"].get("content") or ""
    return (content or ch["message"].get("reasoning") or "",
            (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
            u.get("cost") or 0)


def one_cell(api_key, entry, order, prompt_key):
    model_id, name, group = entry
    prompt = QUESTIONS[prompt_key] + ORDERS[order]
    runs = []
    for i in range(RUNS):
        parsed = None
        for attempt in range(3):
            try:
                text, rtok, cost = call(api_key, model_id, prompt)
                parsed = parse(text, order)
                if parsed:
                    parsed.update({"reasoning_tokens": rtok, "cost": cost})
                    break
            except Exception as e:
                parsed = None
                last = f"{type(e).__name__}: {e}"
            if attempt < 2:
                time.sleep(2 + random.uniform(0, 2))
        runs.append(parsed or {"lower": None, "upper": None})
        time.sleep(0.4 + random.uniform(0, 1.0))

    valid = [r for r in runs if r["lower"] is not None]
    lo = sum(r["lower"] for r in valid) / len(valid) if valid else None
    hi = sum(r["upper"] for r in valid) / len(valid) if valid else None
    print(f"  {name:20s} {group:9s} {prompt_key:14s} {order:20s} "
          f"{'--' if lo is None else f'{lo:.3f}-{hi:.3f}'} ({len(valid)}/{RUNS})", flush=True)
    return {"model_id": model_id, "display_name": name, "group": group,
            "prompt_key": prompt_key, "order": order,
            "avg_lower": lo, "avg_upper": hi, "valid_runs": len(valid), "runs": runs}


def main():
    api_key = load_api_key()
    cells = [(e, o, p) for e in MODELS for o in ORDERS for p in QUESTIONS]
    print(f"{len(cells)} cells x {RUNS} runs = {len(cells) * RUNS} calls")
    print("=" * 92, flush=True)

    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(one_cell, api_key, e, o, p): (e, o, p) for e, o, p in cells}
        for f in as_completed(futs):
            try:
                results.append(f.result())
            except Exception as exc:
                e, o, p = futs[f]
                print(f"  ERROR {e[1]} {o} {p}: {exc}", flush=True)

    out = Path(__file__).parent / "side_study_format_order.json"
    out.write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runs_per_cell": RUNS,
        "orders": ORDERS,
        "questions": QUESTIONS,
        "cells": results,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    spend = sum(r.get("cost") or 0 for c in results for r in c["runs"])
    print("=" * 92)
    print(f"Saved {out}  |  cells: {len(results)}  |  spend: ${spend:.4f}")


if __name__ == "__main__":
    main()
