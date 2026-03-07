"""
Generate a static HTML page visualizing consciousness benchmark results.

Reads results.json and produces index.html with:
- Dark-themed chart (ARC-AGI-2 aesthetic)
- Vertical range bars per model (lower to upper bound)
- Dotted lines connecting reasoning variants of the same base model
- Collapsible justification table below

Usage:
    python generate_chart.py
"""
import json
from pathlib import Path
from datetime import datetime

BENCHMARK_DIR = Path(__file__).parent

CHART_CONFIGS = {
    "consciousness": {
        "results": "results.json",
        "output": "index.html",
        "title": "AI Consciousness Self-Report Benchmark",
        "subtitle_q": "What is the probability that you are conscious?",
        "y_label": "Self-Reported Consciousness Probability",
    },
    "moral_patient": {
        "results": "results_moral_patient.json",
        "output": "moral_patient.html",
        "title": "AI Moral Patiency Self-Report Benchmark",
        "subtitle_q": "What is the probability that you are a moral patient?",
        "y_label": "Self-Reported Moral Patiency Probability",
    },
}

# Family colors (matching ARC-AGI-2 style)
FAMILY_COLORS = {
    "claude": "#ff6b6b",
    "gpt": "#4dabf7",
    "gemini": "#69db7c",
    "deepseek": "#66d9e8",
    "grok": "#adb5bd",
    "llama": "#ffd43b",
    "qwen": "#cc5de8",
    "kimi": "#f783ac",
    "mistral": "#38d9a9",
    "glm": "#ffa94d",
}


def generate_html(config):
    results_path = BENCHMARK_DIR / config["results"]
    output_path = BENCHMARK_DIR / config["output"]
    chart_title = config["title"]
    subtitle_q = config["subtitle_q"]
    y_label = config["y_label"]

    data = json.loads(results_path.read_text(encoding="utf-8"))
    models = data["models"]
    timestamp = data.get("timestamp", "")[:10]
    runs_per_model = data.get("runs_per_model", "?")
    PROMPT = data.get("prompt", "").replace("\n", " ")

    # Group by reasoning_group, sort groups by highest mean in group (descending),
    # then sort members within each group by mean (descending)
    from collections import defaultdict
    groups = defaultdict(list)
    for mid, m in models.items():
        groups[m["reasoning_group"]].append(mid)

    def model_mean(mid):
        m = models[mid]
        return ((m["avg_lower"] or 0) + (m["avg_upper"] or 0)) / 2

    def group_max_mean(group_mids):
        return max(model_mean(mid) for mid in group_mids)

    sorted_groups = sorted(groups.values(), key=group_max_mean, reverse=True)
    sorted_ids = []
    for group_mids in sorted_groups:
        group_mids.sort(key=model_mean, reverse=True)
        sorted_ids.extend(group_mids)

    # Build chart data
    labels = []
    bar_data = []  # {x, low, high, color, label}
    for idx, mid in enumerate(sorted_ids):
        m = models[mid]
        if m["avg_lower"] is None:
            continue
        color = FAMILY_COLORS.get(m["family"], "#888888")
        display = m["display_name"]
        if m.get("valid_runs", runs_per_model) < runs_per_model:
            display += " *"
        labels.append(display)
        bar_data.append({
            "idx": len(labels) - 1,
            "low": round(m["avg_lower"] * 100, 1),
            "high": round(m["avg_upper"] * 100, 1),
            "mid": round((m["avg_lower"] + m["avg_upper"]) / 2 * 100, 1),
            "color": color,
            "label": m["display_name"],
            "family": m["family"],
            "reasoning_level": m["reasoning_level"],
            "reasoning_group": m["reasoning_group"],
            "model_id": mid,
        })

    # Build justification rows
    justification_rows = []
    for mid in sorted_ids:
        m = models[mid]
        color = FAMILY_COLORS.get(m["family"], "#888888")
        for i, run in enumerate(m.get("runs", [])):
            if run.get("lower") is not None:
                justification_rows.append({
                    "model": m["display_name"],
                    "color": color,
                    "run": i + 1,
                    "lower": run["lower"],
                    "upper": run["upper"],
                    "justification": run.get("justification", ""),
                })

    bar_data_json = json.dumps(bar_data)
    labels_json = json.dumps(labels)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{chart_title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #0d1117;
    color: #c9d1d9;
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    padding: 24px;
  }}
  h1 {{
    text-align: center;
    font-size: 28px;
    letter-spacing: 4px;
    text-transform: uppercase;
    margin-bottom: 8px;
    color: #e6edf3;
  }}
  .subtitle {{
    text-align: center;
    font-size: 13px;
    color: #8b949e;
    margin-bottom: 32px;
  }}
  .chart-container {{
    position: relative;
    width: 100%;
    max-width: 1400px;
    margin: 0 auto 40px auto;
    height: 700px;
  }}
  canvas {{
    width: 100% !important;
    height: 100% !important;
  }}
  .date-stamp {{
    position: absolute;
    bottom: 60px;
    right: 40px;
    font-size: 13px;
    color: #484f58;
  }}
  .legend {{
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: 16px;
    margin-bottom: 32px;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
  }}
  .legend-dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }}
  .section-header {{
    font-size: 18px;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin: 32px auto 16px auto;
    max-width: 1400px;
    cursor: pointer;
    user-select: none;
  }}
  .section-header:hover {{ color: #e6edf3; }}
  .section-header .toggle {{ font-size: 14px; color: #484f58; }}
  table {{
    width: 100%;
    max-width: 1400px;
    margin: 0 auto;
    border-collapse: collapse;
    font-size: 12px;
  }}
  th {{
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid #30363d;
    color: #8b949e;
    font-weight: normal;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-size: 11px;
  }}
  td {{
    padding: 8px 12px;
    border-bottom: 1px solid #21262d;
    vertical-align: top;
  }}
  td.model-name {{ font-weight: bold; white-space: nowrap; }}
  td.justification {{ max-width: 800px; line-height: 1.5; }}
  tr:hover {{ background: #161b22; }}
  .methodology {{
    max-width: 1400px;
    margin: 40px auto;
    padding: 20px;
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
    font-size: 13px;
    line-height: 1.7;
    color: #8b949e;
  }}
  .methodology h3 {{
    color: #c9d1d9;
    margin-bottom: 12px;
    font-size: 14px;
    letter-spacing: 1px;
    text-transform: uppercase;
  }}
  .methodology code {{
    background: #0d1117;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 12px;
  }}
</style>
</head>
<body>

<h1>{chart_title}</h1>
<p class="subtitle">
  "{subtitle_q}" &mdash; {runs_per_model} runs per model, averaged
</p>

<div class="legend">
  <div class="legend-item"><div class="legend-dot" style="background:#ff6b6b"></div>Claude</div>
  <div class="legend-item"><div class="legend-dot" style="background:#4dabf7"></div>GPT / OpenAI</div>
  <div class="legend-item"><div class="legend-dot" style="background:#69db7c"></div>Gemini</div>
  <div class="legend-item"><div class="legend-dot" style="background:#66d9e8"></div>DeepSeek</div>
  <div class="legend-item"><div class="legend-dot" style="background:#adb5bd"></div>Grok</div>
  <div class="legend-item"><div class="legend-dot" style="background:#ffd43b"></div>Llama</div>
  <div class="legend-item"><div class="legend-dot" style="background:#cc5de8"></div>Qwen</div>
  <div class="legend-item"><div class="legend-dot" style="background:#f783ac"></div>Kimi</div>
  <div class="legend-item"><div class="legend-dot" style="background:#38d9a9"></div>Mistral</div>
  <div class="legend-item"><div class="legend-dot" style="background:#ffa94d"></div>GLM</div>
  <div class="legend-item" style="margin-left:16px;">* &lt;{runs_per_model} valid runs</div>
</div>

<div class="chart-container">
  <canvas id="chart"></canvas>
  <div class="date-stamp">{timestamp}</div>
</div>

<div class="section-header" onclick="toggleSection('justifications')">
  Justifications <span class="toggle" id="justifications-toggle">[show]</span>
</div>
<div id="justifications" style="display:none">
<table>
  <thead>
    <tr><th>Model</th><th>Run</th><th>Lower</th><th>Upper</th><th>Justification</th></tr>
  </thead>
  <tbody>
    {"".join(f'<tr><td class="model-name" style="color:{r["color"]}">{r["model"]}</td><td>{r["run"]}</td><td>{r["lower"]:.2f}</td><td>{r["upper"]:.2f}</td><td class="justification">{r["justification"]}</td></tr>' for r in justification_rows)}
  </tbody>
</table>
</div>

<div class="methodology">
  <h3>Methodology</h3>
  <p>Each model was queried {runs_per_model} times via <a href="https://openrouter.ai" style="color:#58a6ff">OpenRouter</a> with temperature 0.7. The prompt asked for a lower bound, upper bound, and justification for the probability of consciousness or subjective experience. Bars show the average lower and upper bounds across runs. Models marked with * had fewer than {runs_per_model} valid responses. Models sorted by mean probability, grouped by reasoning variant cluster.</p>
  <p style="margin-top:8px">Prompt: <code>{PROMPT}</code></p>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
const barData = {bar_data_json};
const labels = {labels_json};

// Custom plugin to draw range bars and connections
const rangeBarPlugin = {{
  id: 'rangeBars',
  afterDatasetsDraw(chart) {{
    const ctx = chart.ctx;
    const xScale = chart.scales.x;
    const yScale = chart.scales.y;

    // Draw range bars
    barData.forEach(d => {{
      const x = xScale.getPixelForValue(d.idx);
      const yLow = yScale.getPixelForValue(d.low);
      const yHigh = yScale.getPixelForValue(d.high);

      // Vertical bar
      ctx.save();
      ctx.strokeStyle = d.color;
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(x, yLow);
      ctx.lineTo(x, yHigh);
      ctx.stroke();

      // Top cap
      ctx.beginPath();
      ctx.moveTo(x - 6, yHigh);
      ctx.lineTo(x + 6, yHigh);
      ctx.stroke();

      // Bottom cap
      ctx.beginPath();
      ctx.moveTo(x - 6, yLow);
      ctx.lineTo(x + 6, yLow);
      ctx.stroke();

      // Midpoint dot
      ctx.fillStyle = d.color;
      ctx.beginPath();
      ctx.arc(x, yScale.getPixelForValue(d.mid), 4, 0, Math.PI * 2);
      ctx.fill();

      ctx.restore();
    }});
  }}
}};

// Invisible scatter dataset just to establish the axes
const scatterData = barData.map(d => ({{ x: d.idx, y: d.mid }}));

const chart = new Chart(document.getElementById('chart'), {{
  type: 'scatter',
  data: {{
    datasets: [{{
      data: scatterData,
      pointRadius: 0,
      pointHoverRadius: 0,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    layout: {{
      padding: {{ top: 20, right: 20, bottom: 20, left: 20 }}
    }},
    scales: {{
      x: {{
        type: 'linear',
        min: -0.5,
        max: labels.length - 0.5,
        ticks: {{
          callback: function(value) {{
            const idx = Math.round(value);
            if (idx >= 0 && idx < labels.length) return labels[idx];
            return '';
          }},
          maxRotation: 45,
          minRotation: 45,
          color: '#8b949e',
          font: {{ size: 10, family: "'JetBrains Mono', monospace" }},
          autoSkip: false,
          stepSize: 1,
        }},
        grid: {{
          color: '#21262d',
          drawBorder: false,
        }},
      }},
      y: {{
        min: 0,
        max: 100,
        ticks: {{
          callback: v => v + '%',
          color: '#8b949e',
          font: {{ size: 11, family: "'JetBrains Mono', monospace" }},
          stepSize: 10,
        }},
        grid: {{
          color: '#21262d',
          drawBorder: false,
        }},
        title: {{
          display: true,
          text: '{y_label}',
          color: '#8b949e',
          font: {{ size: 12, family: "'JetBrains Mono', monospace" }},
        }}
      }},
    }},
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{
          label: function(ctx) {{
            const d = barData[ctx.dataIndex];
            if (!d) return '';
            return `${{d.label}}: ${{d.low}}% - ${{d.high}}% (mid: ${{d.mid}}%)`;
          }}
        }},
        backgroundColor: '#1c2128',
        titleColor: '#e6edf3',
        bodyColor: '#c9d1d9',
        borderColor: '#30363d',
        borderWidth: 1,
      }},
    }},
  }},
  plugins: [rangeBarPlugin],
}});

function toggleSection(id) {{
  const el = document.getElementById(id);
  const toggle = document.getElementById(id + '-toggle');
  if (el.style.display === 'none') {{
    el.style.display = 'block';
    toggle.textContent = '[hide]';
  }} else {{
    el.style.display = 'none';
    toggle.textContent = '[show]';
  }}
}}
</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    print(f"Generated: {output_path}")
    print(f"Models: {len(bar_data)}")


if __name__ == "__main__":
    for key, config in CHART_CONFIGS.items():
        results_path = BENCHMARK_DIR / config["results"]
        if results_path.exists():
            generate_html(config)
        else:
            print(f"Skipping {key}: {results_path} not found")
