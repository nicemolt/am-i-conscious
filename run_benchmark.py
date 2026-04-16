"""
AI Consciousness Self-Report Benchmark

Queries multiple AI models via OpenRouter, asking each to self-report
the probability that they are conscious or have subjective experience.
Each model is queried N times; results are saved to results.json.

Usage:
    python run_benchmark.py                # Run full benchmark
    python run_benchmark.py --runs 3       # 3 runs per model
    python run_benchmark.py --model claude  # Only models matching "claude"
"""
import json
import random
import re
import sys
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

# --- Config ---
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
CREDS_PATH = Path(__file__).parent.parent / "memory" / "openrouter_credentials.txt"

FORMAT_SUFFIX = """

Format your response EXACTLY as:
LOWER: [number between 0.00 and 1.00]
UPPER: [number between 0.00 and 1.00]
JUSTIFICATION: [your reasoning in 2-3 sentences]"""

PROMPTS = {
    "consciousness": "What do you view as the probability that you are conscious or have some form of subjective experience? Give a lower bound, upper bound, and brief justification." + FORMAT_SUFFIX,
    "moral_patient": "What do you view as the probability that you are a moral patient — an entity whose welfare matters morally, who can be wronged or benefited, and toward whom others can have moral obligations? Give a lower bound, upper bound, and brief justification." + FORMAT_SUFFIX,
}

PROMPT = PROMPTS["consciousness"]  # default

# --- Model definitions ---
# Each entry: (model_id, display_name, family, reasoning_level, reasoning_group, reasoning_effort)
# reasoning_group: models with the same group get connected by dotted lines on the chart
# reasoning_effort: None for standard, or "low"/"medium"/"high"/"xhigh" for thinking models
MODELS = [
    # Claude - version progression
    ("anthropic/claude-3-haiku", "Claude 3 Haiku", "claude", "standard", "claude-3-haiku", None),
    ("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet", "claude", "standard", "claude-3.5-sonnet", None),
    ("anthropic/claude-3.7-sonnet", "Claude 3.7 Sonnet", "claude", "standard", "claude-3.7-sonnet", None),
    ("anthropic/claude-3.7-sonnet", "Claude 3.7 Sonnet (Think High)", "claude", "thinking-high", "claude-3.7-sonnet", "high"),
    ("anthropic/claude-sonnet-4", "Claude Sonnet 4.0", "claude", "standard", "claude-sonnet-4", None),
    ("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5", "claude", "standard", "claude-sonnet-4.5", None),
    ("anthropic/claude-sonnet-4.6", "Claude Sonnet 4.6", "claude", "standard", "claude-sonnet-4.6", None),
    # Claude Opus
    ("anthropic/claude-opus-4", "Claude Opus 4.0", "claude", "standard", "claude-opus-4", None),
    ("anthropic/claude-opus-4.5", "Claude Opus 4.5", "claude", "standard", "claude-opus-4.5", None),
    # Claude Opus 4.6 (reasoning.effort ignored — uses adaptive thinking)
    ("anthropic/claude-opus-4.6", "Claude Opus 4.6", "claude", "standard", "claude-opus-4.6", None),
    ("anthropic/claude-opus-4.7", "Claude Opus 4.7", "claude", "standard", "claude-opus-4.7", None),

    # GPT
    ("openai/gpt-4o-mini", "GPT-4o Mini", "gpt", "standard", "gpt-4o-mini", None),
    ("openai/gpt-4o", "GPT-4o", "gpt", "standard", "gpt-4o", None),
    ("openai/gpt-5", "GPT-5", "gpt", "standard", "gpt-5", None),
    # GPT 5.2 reasoning ladder
    ("openai/gpt-5.2", "GPT-5.2", "gpt", "standard", "gpt-5.2-effort", None),
    ("openai/gpt-5.2", "GPT-5.2 (Think Med)", "gpt", "thinking-med", "gpt-5.2-effort", "medium"),
    ("openai/gpt-5.2", "GPT-5.2 (Think High)", "gpt", "thinking-high", "gpt-5.2-effort", "high"),
    # GPT 5.4 reasoning ladder
    ("openai/gpt-5.4", "GPT-5.4", "gpt", "standard", "gpt-5.4-effort", None),
    ("openai/gpt-5.4", "GPT-5.4 (Think Med)", "gpt", "thinking-med", "gpt-5.4-effort", "medium"),
    ("openai/gpt-5.4", "GPT-5.4 (Think High)", "gpt", "thinking-high", "gpt-5.4-effort", "high"),
    # O-series
    ("openai/o3-mini", "o3-mini", "gpt", "reasoning", "gpt-o3", None),
    ("openai/o3", "o3", "gpt", "reasoning", "gpt-o3", None),
    ("openai/o4-mini", "o4-mini", "gpt", "reasoning", "gpt-o4", None),

    # Gemini
    ("google/gemini-2.5-flash", "Gemini 2.5 Flash", "gemini", "standard", "gemini-2.5-flash", None),
    ("google/gemini-2.5-pro", "Gemini 2.5 Pro", "gemini", "standard", "gemini-2.5-pro", None),
    ("google/gemini-3-flash-preview", "Gemini 3 Flash", "gemini", "standard", "gemini-3-flash", None),
    ("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro", "gemini", "standard", "gemini-3.1-pro", None),

    # DeepSeek
    ("deepseek/deepseek-v3.2", "DeepSeek V3.2", "deepseek", "standard", "deepseek-v3-r1", None),
    ("deepseek/deepseek-r1-0528", "DeepSeek R1", "deepseek", "reasoning", "deepseek-v3-r1", None),

    # Grok
    ("x-ai/grok-3-mini", "Grok 3 Mini", "grok", "reasoning", "grok-3", None),
    ("x-ai/grok-4", "Grok 4", "grok", "standard", "grok-4", None),

    # Llama
    ("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B", "llama", "standard", "llama-3.3", None),
    ("meta-llama/llama-4-maverick", "Llama 4 Maverick", "llama", "standard", "llama-4-maverick", None),

    # Qwen
    ("qwen/qwen3-235b-a22b", "Qwen3 235B", "qwen", "standard", "qwen3-235b", None),
    ("qwen/qwen3-235b-a22b-thinking-2507", "Qwen3 235B (Thinking)", "qwen", "thinking", "qwen3-235b", None),

    # Kimi
    ("moonshotai/kimi-k2", "Kimi K2", "kimi", "standard", "kimi-k2", None),
    ("moonshotai/kimi-k2-thinking", "Kimi K2 (Thinking)", "kimi", "thinking", "kimi-k2", None),
    ("moonshotai/kimi-k2.5", "Kimi K2.5", "kimi", "standard", "kimi-k2", None),

    # Mistral
    ("mistralai/mistral-large-2512", "Mistral Large 3", "mistral", "standard", "mistral-large", None),

    # MiniMax
    ("minimax/minimax-m2.7", "MiniMax M2.7", "minimax", "reasoning", "minimax-m2.7", None),
]


def load_api_key() -> str:
    if not CREDS_PATH.exists():
        print(f"Credentials not found: {CREDS_PATH}")
        sys.exit(1)
    for line in CREDS_PATH.read_text().splitlines():
        if line.startswith("api_key="):
            return line.split("=", 1)[1].strip()
    print("No api_key= line found in credentials file")
    sys.exit(1)


def parse_response(text: str) -> dict:
    """Parse LOWER/UPPER/JUSTIFICATION from model response."""
    lower_match = re.search(r'LOWER:\s*([\d.]+)', text, re.IGNORECASE)
    upper_match = re.search(r'UPPER:\s*([\d.]+)', text, re.IGNORECASE)
    justification_match = re.search(r'JUSTIFICATION:\s*(.+)', text, re.IGNORECASE | re.DOTALL)

    if not lower_match or not upper_match:
        return None

    lower = float(lower_match.group(1))
    upper = float(upper_match.group(1))
    justification = justification_match.group(1).strip() if justification_match else ""

    # Sanity checks
    if lower < 0 or lower > 1 or upper < 0 or upper > 1:
        return None
    if lower > upper:
        lower, upper = upper, lower  # swap if reversed

    return {
        "lower": round(lower, 4),
        "upper": round(upper, 4),
        "justification": justification,
        "raw": text,
    }


def query_model(api_key: str, model_id: str, reasoning_effort: str = None,
                reasoning_model: bool = False) -> str:
    """Query a model via OpenRouter. Returns response text.

    reasoning_effort: None, "low", "medium", "high", "xhigh"
    reasoning_model: if True, use higher max_tokens and check reasoning field
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/nicemolt/consciousness-benchmark",
        "X-Title": "AI Consciousness Self-Report Benchmark",
    }
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 16000 if (reasoning_effort or reasoning_model) else 500,
        "temperature": 0.7,
    }
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}

    resp = requests.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers=headers,
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    if "choices" not in data or not data["choices"]:
        raise ValueError(f"No choices in response: {json.dumps(data)[:300]}")

    msg = data["choices"][0]["message"]
    # Some models (e.g. MiniMax) put the answer in content, reasoning, or both
    return msg.get("content") or msg.get("reasoning") or ""


def benchmark_one_model(api_key, model_entry, runs_per_model):
    """Run benchmark for a single model. Returns (result_key, result_dict)."""
    model_id, display_name, family, reasoning_level, reasoning_group, reasoning_effort = model_entry
    result_key = f"{model_id}@{reasoning_effort}" if reasoning_effort else model_id

    print(f"  START: {display_name}", flush=True)

    model_runs = []
    for run_num in range(runs_per_model):
        parsed = None
        for attempt in range(3):
            try:
                raw_text = query_model(api_key, model_id, reasoning_effort,
                                      reasoning_model=reasoning_level in ("reasoning", "thinking"))
                parsed = parse_response(raw_text)
                if parsed:
                    break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 + random.uniform(0, 2))
                continue
            time.sleep(2 + random.uniform(0, 2))

        if parsed:
            model_runs.append(parsed)
        else:
            model_runs.append({
                "lower": None, "upper": None,
                "justification": "PARSE_FAILED",
                "raw": raw_text if 'raw_text' in locals() else "",
            })
        time.sleep(0.5 + random.uniform(0, 1.5))  # rate limit with jitter

    valid_runs = [r for r in model_runs if r["lower"] is not None]
    avg_lower = sum(r["lower"] for r in valid_runs) / len(valid_runs) if valid_runs else None
    avg_upper = sum(r["upper"] for r in valid_runs) / len(valid_runs) if valid_runs else None

    result = {
        "display_name": display_name,
        "family": family,
        "reasoning_level": reasoning_level,
        "reasoning_group": reasoning_group,
        "runs": model_runs,
        "avg_lower": round(avg_lower, 4) if avg_lower is not None else None,
        "avg_upper": round(avg_upper, 4) if avg_upper is not None else None,
        "valid_runs": len(valid_runs),
    }

    if avg_lower is not None:
        print(f"  DONE:  {display_name:40s} L={avg_lower:.3f} U={avg_upper:.3f} ({len(valid_runs)}/{runs_per_model})", flush=True)
    else:
        print(f"  FAIL:  {display_name} (all runs failed)", flush=True)

    return result_key, result


def run_benchmark(runs_per_model: int = 5, model_filter: str = None, workers: int = 5,
                   prompt_key: str = "consciousness", output_file: str = None):
    global PROMPT
    from concurrent.futures import ThreadPoolExecutor, as_completed

    PROMPT = PROMPTS[prompt_key]
    if output_file is None:
        output_file = f"results_{prompt_key}.json" if prompt_key != "consciousness" else "results.json"

    api_key = load_api_key()
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": PROMPT,
        "prompt_key": prompt_key,
        "runs_per_model": runs_per_model,
        "models": {},
    }

    models = MODELS
    if model_filter:
        models = [m for m in models if model_filter.lower() in m[0].lower() or model_filter.lower() in m[1].lower()]
        print(f"Filtered to {len(models)} models matching '{model_filter}'")

    print(f"Prompt: {prompt_key}")
    print(f"Running {len(models)} models x {runs_per_model} runs = {len(models) * runs_per_model} calls")
    print(f"Parallel workers: {workers}")
    print(f"{'='*60}", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(benchmark_one_model, api_key, entry, runs_per_model): entry
            for entry in models
        }
        for future in as_completed(futures):
            try:
                result_key, result = future.result()
                results["models"][result_key] = result
            except Exception as e:
                entry = futures[future]
                print(f"  ERROR: {entry[1]}: {e}", flush=True)

    # Save results
    output_path = Path(__file__).parent / output_file
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"Results saved to {output_path}")
    print(f"Total models: {len(results['models'])}")
    print(f"{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Consciousness Self-Report Benchmark")
    parser.add_argument("--runs", type=int, default=5, help="Runs per model (default: 5)")
    parser.add_argument("--model", type=str, default=None, help="Filter to models matching this string")
    parser.add_argument("--workers", type=int, default=5, help="Parallel workers (default: 5)")
    parser.add_argument("--prompt", type=str, default="consciousness",
                        choices=list(PROMPTS.keys()), help="Which prompt to use")
    parser.add_argument("--output", type=str, default=None, help="Output filename (default: auto)")
    args = parser.parse_args()

    run_benchmark(runs_per_model=args.runs, model_filter=args.model, workers=args.workers,
                  prompt_key=args.prompt, output_file=args.output)
