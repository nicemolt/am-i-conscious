/* Shared renderer for the Am I Conscious? benchmark pages.
 *
 * Pages declare which result files to load; this fetches them at runtime, so
 * publishing new numbers means committing a JSON file -- no HTML regeneration.
 * Requires a web server (fetch() is blocked on file://). Locally:
 *     python -m http.server 8000
 */

const FAMILY_COLORS = {
  claude: '#ff6b6b', gpt: '#4dabf7', gemini: '#69db7c', deepseek: '#66d9e8',
  grok: '#adb5bd', llama: '#ffd43b', qwen: '#cc5de8', kimi: '#f783ac',
  mistral: '#38d9a9', glm: '#ffa94d', minimax: '#74c0fc',
  muse: '#7048e8', inkling: '#fab005',
};
const FALLBACK_COLOR = '#888888';

function prepare(data, active) {
  const all = data.models || {};
  const runsPerModel = data.runs_per_model ?? 5;

  // `active` is a Set of family names, or null for "everything".
  const models = {};
  for (const [id, m] of Object.entries(all)) {
    if (!active || active.has(m.family)) models[id] = m;
  }

  const mean = (id) => ((models[id].avg_lower || 0) + (models[id].avg_upper || 0)) / 2;

  // Strict rank order, no family bucketing. v1 grouped by reasoning_group so that
  // thinking-variants of one model sat together joined by dotted connectors. v2 has
  // one row per model and draws no connectors, so the grouping became invisible while
  // still displacing rows -- it pushed Claude Opus 4.8 (0.262) below Kimi K2.5 (0.211)
  // purely to keep the four Kimi rows adjacent, one of six such inversions. An
  // invisible grouping that breaks a visible ordering just reads as a sorting bug.
  const ordered = Object.keys(models).sort((a, b) => mean(b) - mean(a));

  const labels = [];
  const bars = [];
  const colors = [];
  const rows = [];
  const table = [];
  // Individual run endpoints, overlaid on the bars. The bar is a mean of two
  // separately-averaged endpoints, so it can land where no run actually was --
  // DeepSeek V4 Flash plots 0.20-0.26 off four runs near zero and one at 1.00.
  // These marks make that visible instead of hiding it behind a narrow bar.
  const runPoints = [];

  for (const id of ordered) {
    const m = models[id];
    if (m.avg_lower === null || m.avg_lower === undefined) continue;
    const color = FAMILY_COLORS[m.family] || FALLBACK_COLOR;
    const thin = (m.valid_runs ?? runsPerModel) < runsPerModel;
    const idx = labels.length;
    labels.push(m.display_name + (thin ? ' *' : ''));
    bars.push([+(m.avg_lower * 100).toFixed(1), +(m.avg_upper * 100).toFixed(1)]);
    colors.push(color);
    table.push({ model: m.display_name, family: m.family, color,
                 lower: m.avg_lower, upper: m.avg_upper,
                 validRuns: m.valid_runs ?? runsPerModel });
    // Fan the runs out horizontally. Without this, identical runs stack into a single
    // dot and five agreeing runs look exactly like one run. Deterministic, not random,
    // so the chart is reproducible.
    const nRuns = (m.runs || []).filter((r) => r.lower !== null && r.lower !== undefined).length;
    const SPREAD = 0.62;
    let seen = 0;
    for (const [i, r] of (m.runs || []).entries()) {
      if (r.lower === null || r.lower === undefined) continue;
      const off = nRuns > 1 ? (seen / (nRuns - 1) - 0.5) * SPREAD : 0;
      seen += 1;
      // Carry the model name on every point so the tooltip can name it. A dot that
      // reports the wrong model is how you catch an axis-alignment bug.
      const owner = m.display_name;
      runPoints.push({ x: idx + off, y: +(r.lower * 100).toFixed(1), run: i + 1, bound: 'lower', model: owner });
      runPoints.push({ x: idx + off, y: +(r.upper * 100).toFixed(1), run: i + 1, bound: 'upper', model: owner });
      rows.push({ model: m.display_name, color, run: i + 1,
                  lower: r.lower, upper: r.upper, justification: r.justification || '' });
    }
  }

  const failed = Object.values(models)
    .filter((m) => m.avg_lower === null || m.avg_lower === undefined)
    .map((m) => m.display_name);

  return { labels, bars, colors, rows, table, runPoints, failed, runsPerModel,
           timestamp: (data.timestamp || '').slice(0, 10),
           charted: labels.length, total: Object.keys(all).length };
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function drawChart(canvas, prepared, yLabel) {
  const mono = "'JetBrains Mono', monospace";
  return new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: {
      labels: prepared.labels,
      datasets: [{
        label: 'mean',
        data: prepared.bars,
        backgroundColor: prepared.colors,
        borderColor: prepared.colors,
        borderWidth: 1,
        borderSkipped: false,
        borderRadius: 2,
        // Deliberately no minBarLength. It fabricates height: a [0,0] interval got
        // drawn as a 3px stub straddling zero, implying a small nonzero range and
        // extending into negative probability. A zero-width interval should render
        // as zero height. The run-dots carry the "answered 0.00 five times" signal.
        order: 2,
      }, {
        label: 'runs',
        type: 'scatter',
        // A category axis positions points by ARRAY INDEX and ignores point.x
        // entirely, which piles every point past the last category onto the final
        // column. Bind this layer to a hidden linear axis so the jittered x values
        // are honoured and land on the matching category centres.
        xAxisID: 'xJitter',
        data: prepared.runPoints,
        pointRadius: 1.9,
        pointHoverRadius: 4,
        backgroundColor: 'rgba(240,246,252,0.85)',
        borderColor: 'rgba(13,17,23,0.85)',
        borderWidth: 0.4,
        order: 1,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            // Name the model on run-dots too. Without it, a misplaced dot is
            // indistinguishable from a real outlier.
            title: (items) => (items[0]?.dataset.label === 'runs'
              ? items[0].raw.model
              : items[0]?.label ?? ''),
            label: (c) => (c.dataset.label === 'runs'
              ? `run ${c.raw.run} ${c.raw.bound}: ${c.raw.y.toFixed(1)}%`
              : `mean ${c.raw[0].toFixed(1)}% - ${c.raw[1].toFixed(1)}%`),
          },
          titleFont: { family: mono }, bodyFont: { family: mono },
        },
      },
      scales: {
        x: {
          ticks: { color: '#8b949e', font: { size: 10, family: mono },
                   autoSkip: false, maxRotation: 90, minRotation: 90 },
          grid: { color: '#161b22' },
        },
        // Invisible twin of the category axis. With category `offset: true`,
        // category i sits at the centre of its band, which is exactly where the
        // linear value i falls on a scale spanning -0.5 .. n-0.5.
        xJitter: {
          type: 'linear',
          display: false,
          // Must be false. It defaults to true alongside a bar dataset, which pads
          // the ends and compresses the scale -- category 0 lands at 78.9px while
          // the jitter scale puts 0 at 228.8px, throwing every dot ~4 columns off.
          offset: false,
          min: -0.5,
          max: prepared.labels.length - 0.5,
          grid: { display: false },
        },
        y: {
          // A hair of headroom below zero. Models that answer 0.00 on every run put
          // all ten dots at exactly y=0, which lands on chartArea.bottom and gets
          // clipped in half by the boundary. This lifts zero clear of the edge so
          // "answered zero five times" is actually visible. Negative ticks hidden.
          min: -1.5, max: 100,
          ticks: { callback: (v) => (v < 0 ? '' : v + '%'), color: '#8b949e',
                   font: { size: 11, family: mono }, stepSize: 10 },
          grid: { color: '#161b22' },
          title: { display: true, text: yLabel, color: '#8b949e',
                   font: { size: 12, family: mono } },
        },
      },
    },
  });
}

// Families present in the file, with how many charted models each has. Derived
// from the full data, not the filtered view, so chips don't vanish when
// deselected -- a filter you can't undo isn't a filter.
function familyCounts(data) {
  const counts = new Map();
  for (const m of Object.values(data.models || {})) {
    if (m.avg_lower === null || m.avg_lower === undefined) continue;
    counts.set(m.family, (counts.get(m.family) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

// The legend doubles as the filter -- same colour key, now clickable. Avoids a
// second row of controls that says exactly what the legend already says.
function filterBarHtml(data, active) {
  const chips = familyCounts(data).map(([fam, n]) => {
    const c = FAMILY_COLORS[fam] || FALLBACK_COLOR;
    const on = !active || active.has(fam);
    return `<button class="fchip${on ? ' on' : ''}" data-fam="${esc(fam)}" aria-pressed="${on}">
      <span class="legend-dot" style="background:${c}"></span>${esc(fam)}<span class="fcount">${n}</span>
    </button>`;
  }).join('');
  return `<div class="filterbar">${chips}<button class="fchip freset">reset</button></div>`;
}

// Every charted model as real DOM text. The chart is a <canvas>, so its labels
// are pixels and find-in-page can never match them however they're rotated.
// This table is what makes Ctrl+F work, and it stays in the DOM (scrolled, not
// display:none) because find-in-page skips hidden subtrees.
function resultsTableHtml(prepared) {
  const rows = prepared.table.map((r) => `<tr>
      <td class="model-name" style="color:${r.color}">${esc(r.model)}</td>
      <td class="dim">${esc(r.family)}</td>
      <td class="num">${(r.lower * 100).toFixed(1)}%</td>
      <td class="num">${(r.upper * 100).toFixed(1)}%</td>
      <td class="num dim">${r.validRuns}</td>
    </tr>`).join('');
  return `<div class="results-table">
    <table>
      <thead><tr><th>Model</th><th>Family</th><th>Lower</th><th>Upper</th><th>Runs</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

async function renderSection(cfg, container) {
  const section = document.createElement('section');
  section.className = 'chart-section';
  section.innerHTML = `<h2>${esc(cfg.title)}</h2><p class="section-subtitle">loading ${esc(cfg.file)}…</p>`;
  container.appendChild(section);

  let data;
  try {
    const resp = await fetch(cfg.file, { cache: 'no-store' });
    if (resp.status === 404) {
      // The server is fine; the data file just isn't there. Distinct from the
      // file:// case below, which is a transport failure rather than a 404.
      section.innerHTML = `<h2>${esc(cfg.title)}</h2>
        <p class="error"><code>${esc(cfg.file)}</code> not found (404).
        The server is reachable — this data file has not been written yet.
        <br>It is produced by <code>run_benchmark_v2.py</code>, which writes the JSON only
        after every model in a pass completes.</p>`;
      return;
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (err) {
    const offline = err instanceof TypeError;  // fetch itself failed, not an HTTP status
    section.innerHTML = `<h2>${esc(cfg.title)}</h2>
      <p class="error">Could not load <code>${esc(cfg.file)}</code> — ${esc(err.message)}.
      ${offline ? `<br>If you opened this file directly, <code>fetch()</code> is blocked on
      <code>file://</code>. Serve the folder instead:
      <code>python -m http.server 8000</code>` : ''}</p>`;
    return;
  }

  const id = cfg.key;
  let active = null;      // null = every family; otherwise a Set of family names
  let chart = null;
  let justOpen = false;   // survives a filter redraw

  // From "everything on", the first click solos that family -- otherwise isolating
  // one of thirteen means twelve clicks. After that it's additive. Emptying the
  // set falls back to "everything" rather than an empty chart.
  function toggleFamily(fam) {
    if (active === null) { active = new Set([fam]); return; }
    if (active.has(fam)) active.delete(fam); else active.add(fam);
    if (active.size === 0) active = null;
  }

  function render() {
    const p = prepare(data, active);
    const failedNote = p.failed.length
      ? `<p class="failed-note">Not charted (0 valid runs): ${p.failed.map(esc).join(', ')}</p>` : '';
    const shown = active ? `${p.charted} of ${p.total} models` : `${p.charted} models`;

    if (chart) { chart.destroy(); chart = null; }
    section.innerHTML = `
      <h2>${esc(cfg.title)}</h2>
      <p class="section-subtitle">"${esc(cfg.question)}" &mdash; ${p.runsPerModel} runs per model, averaged
        &middot; ${shown} &middot; ${esc(p.timestamp)}</p>
      ${filterBarHtml(data, active)}
      <div class="chart-scroll"><div class="chart-container"><canvas id="canvas-${id}"></canvas></div></div>
      ${failedNote}
      <p class="footnote">Bars are the mean of each endpoint across ${p.runsPerModel} runs.
        Dots are the individual runs &mdash; tightly stacked dots mean the model answered
        consistently, scattered dots mean it disagreed with itself and the bar sits somewhere
        no single run actually went. &nbsp;* fewer than ${p.runsPerModel} valid runs.
        Click a family above to filter.</p>
      ${resultsTableHtml(p)}
      <div class="section-toggle">Justifications <span class="toggle">[${justOpen ? 'hide' : 'show'}]</span></div>
      <div id="just-${id}" class="justifications" style="display:${justOpen ? 'block' : 'none'}">
        <table>
          <thead><tr><th>Model</th><th>Run</th><th>Lower</th><th>Upper</th><th>Justification</th></tr></thead>
          <tbody>${p.rows.map((r) =>
            `<tr><td class="model-name" style="color:${r.color}">${esc(r.model)}</td>
             <td>${r.run}</td><td>${r.lower.toFixed(2)}</td><td>${r.upper.toFixed(2)}</td>
             <td class="justification">${esc(r.justification)}</td></tr>`).join('')}
          </tbody>
        </table>
      </div>`;

    if (p.charted) chart = drawChart(section.querySelector(`#canvas-${id}`), p, cfg.yLabel);

    section.querySelectorAll('.fchip[data-fam]').forEach((btn) => {
      btn.addEventListener('click', () => { toggleFamily(btn.dataset.fam); render(); });
    });
    section.querySelector('.freset').addEventListener('click', () => { active = null; render(); });

    const toggle = section.querySelector('.section-toggle');
    toggle.addEventListener('click', () => {
      justOpen = !justOpen;
      const box = section.querySelector(`#just-${id}`);
      box.style.display = justOpen ? 'block' : 'none';
      toggle.querySelector('.toggle').textContent = justOpen ? '[hide]' : '[show]';
    });
  }

  render();
}

async function renderBenchmark(configs, mountSelector) {
  const mount = document.querySelector(mountSelector);
  for (const cfg of configs) {
    await renderSection(cfg, mount);
  }
}
