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

// Release dates live in their own file: a release date belongs to the model, not
// to a measurement, so it is not duplicated into every row of four result files.
// Optional -- if it is absent the date view is simply unavailable, and the
// default rank view is unaffected. Regenerate with:
//     python run_benchmark_v2.py --refresh-dates
let _datesPromise = null;
function loadModelDates() {
  if (!_datesPromise) {
    _datesPromise = fetch('model_meta.json', { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => (j && j.released_at) || {})
      .catch(() => ({}));
  }
  return _datesPromise;
}

// Ordinary least squares of y on x. Returns null rather than a meaningless fit
// when there are too few points or no spread on x.
function ols(pts) {
  const n = pts.length;
  if (n < 3) return null;
  const mx = pts.reduce((s, p) => s + p.x, 0) / n;
  const my = pts.reduce((s, p) => s + p.y, 0) / n;
  let sxy = 0, sxx = 0, syy = 0;
  for (const p of pts) {
    const dx = p.x - mx, dy = p.y - my;
    sxy += dx * dy; sxx += dx * dx; syy += dy * dy;
  }
  if (!sxx) return null;
  const slope = sxy / sxx;
  return { slope, intercept: my - slope * mx, r2: syy ? (sxy * sxy) / (sxx * syy) : 0 };
}

const YEAR = 365.25 * 24 * 3600 * 1000;

function prepare(data, active, sortMode, dates) {
  const all = data.models || {};
  const runsPerModel = data.runs_per_model ?? 5;
  const dateOf = (id) => (dates && dates[id]) || null;

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
  let ordered = Object.keys(models).sort((a, b) => mean(b) - mean(a));

  // Date mode drops models with no catalogue date rather than guessing one. A
  // hand-entered date next to an API-derived one is two provenances on one axis.
  let undated = 0;
  if (sortMode === 'date') {
    const dated = ordered.filter((id) => dateOf(id));
    undated = ordered.length - dated.length;
    ordered = dated.sort((a, b) => dateOf(a).localeCompare(dateOf(b)));
  }

  const labels = [];
  const bars = [];
  const colors = [];
  const rows = [];
  const table = [];
  const fitPts = [];
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
                 lower: m.avg_lower, upper: m.avg_upper, released: dateOf(id),
                 validRuns: m.valid_runs ?? runsPerModel });
    const myDots = [];
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
      myDots.push({ y: +(r.lower * 100).toFixed(1), run: i + 1, bound: 'lower', model: owner },
                  { y: +(r.upper * 100).toFixed(1), run: i + 1, bound: 'upper', model: owner });
      rows.push({ model: m.display_name, color, run: i + 1,
                  lower: r.lower, upper: r.upper, justification: r.justification || '' });
    }

    if (dateOf(id)) {
      // Regressed on real elapsed time, never on rank position: releases are not
      // evenly spaced, and treating them as if they were would distort the slope.
      const ms = Date.parse(dateOf(id));
      fitPts.push({ idx, ms, t: ms / YEAR, color, dots: myDots,
                    lower: m.avg_lower * 100, upper: m.avg_upper * 100 });
    }
  }

  const failed = Object.values(models)
    .filter((m) => m.avg_lower === null || m.avg_lower === undefined)
    .map((m) => m.display_name);

  // Date mode puts real time on the x axis. On the category axis every model gets
  // an equal-width column, so a line fitted against elapsed time renders bent --
  // it goes flat between models sharing a release date and steepens across gaps.
  // Spacing the bars by actual date makes the same least-squares fit draw straight,
  // and the release clustering becomes visible instead of being flattened away.
  let timeBars = null, timeDots = null, xRange = null, trend = null;
  if (sortMode === 'date' && fitPts.length) {
    // Models released the same day would sit exactly on top of each other. Fan
    // them a few days apart -- invisible against a multi-year span, but enough
    // that both bars are actually drawn.
    const byDate = new Map();
    for (const p of fitPts) byDate.set(p.ms, (byDate.get(p.ms) || 0) + 1);
    const placed = new Map();
    const NUDGE = 4 * 864e5;
    for (const p of fitPts) {
      const k = byDate.get(p.ms);
      const i = placed.get(p.ms) || 0;
      placed.set(p.ms, i + 1);
      p.px = p.ms + (k > 1 ? (i - (k - 1) / 2) * NUDGE : 0);
    }

    timeBars = fitPts.map((p) => ({ x: p.px, y: [p.lower, p.upper] }));
    timeDots = [];
    for (const p of fitPts) {
      for (const d of p.dots) timeDots.push({ x: p.px, y: d.y, run: d.run, bound: d.bound, model: d.model });
    }
    const xs = fitPts.map((p) => p.px);
    const pad = Math.max((Math.max(...xs) - Math.min(...xs)) * 0.03, 10 * 864e5);
    xRange = { min: Math.min(...xs) - pad, max: Math.max(...xs) + pad };

    if (fitPts.length >= 3) {
      const lo = ols(fitPts.map((p) => ({ x: p.t, y: p.lower })));
      const hi = ols(fitPts.map((p) => ({ x: p.t, y: p.upper })));
      if (lo && hi) {
        // Two endpoints are enough now: same axis units as the fit, so it is a
        // straight line by construction.
        const at = (f, ms) => ({ x: ms, y: f.intercept + f.slope * (ms / YEAR) });
        trend = {
          lower: lo, upper: hi, n: fitPts.length,
          from: table.find((r) => r.released)?.released,
          to: [...table].reverse().find((r) => r.released)?.released,
          lowerLine: [at(lo, xRange.min), at(lo, xRange.max)],
          upperLine: [at(hi, xRange.min), at(hi, xRange.max)],
        };
      }
    }
  }

  return { labels, bars, colors, rows, table, runPoints, failed, runsPerModel,
           trend, undated, sortMode, timeBars, timeDots, xRange,
           barColors: sortMode === 'date' ? fitPts.map((p) => p.color) : colors,
           timestamp: (data.timestamp || '').slice(0, 10),
           charted: labels.length, total: Object.keys(all).length };
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// Fitted lower/upper trends, drawn only in date mode. Bound to the same hidden
// linear axis as the run-dots so they land on category centres.
function trendLines(prepared) {
  if (!prepared.trend) return [];
  const mk = (line, color, label) => ({
    // Trend only exists in date mode, so it always rides the time axis.
    type: 'line', label, xAxisID: 'xTime', data: line,
    borderColor: color, borderWidth: 1.6, borderDash: [6, 4],
    pointRadius: 0, pointHoverRadius: 0, fill: false, tension: 0, order: 0,
  });
  return [mk(prepared.trend.upperLine, 'rgba(255,166,87,0.9)', 'upper trend'),
          mk(prepared.trend.lowerLine, 'rgba(88,166,255,0.9)', 'lower trend')];
}

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function drawChart(canvas, prepared, yLabel) {
  const mono = "'JetBrains Mono', monospace";
  // Boolean, not the array -- `a && b` yields b, and this feeds scale `display`.
  const byTime = prepared.sortMode === 'date' && !!prepared.timeBars;
  // Bars sit on the time axis in date mode, so Chart.js can no longer infer their
  // width from a category band and has to be told.
  const barPx = byTime
    ? Math.max(4, Math.min(16, Math.round(1800 / Math.max(prepared.timeBars.length, 1))))
    : undefined;

  return new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: {
      labels: byTime ? undefined : prepared.labels,
      datasets: [{
        label: 'mean',
        xAxisID: byTime ? 'xTime' : 'x',
        data: byTime ? prepared.timeBars : prepared.bars,
        backgroundColor: prepared.barColors,
        borderColor: prepared.barColors,
        barThickness: barPx,
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
        xAxisID: byTime ? 'xTime' : 'xJitter',
        data: byTime ? prepared.timeDots : prepared.runPoints,
        pointRadius: 1.9,
        pointHoverRadius: 4,
        backgroundColor: 'rgba(240,246,252,0.85)',
        borderColor: 'rgba(13,17,23,0.85)',
        borderWidth: 0.4,
        order: 1,
      }, ...trendLines(prepared)],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            // Name the model on run-dots too. Without it, a misplaced dot is
            // indistinguishable from a real outlier. In date mode the bars have no
            // category label to fall back on, so read the name off the table.
            title: (items) => {
              const it = items[0];
              if (!it) return '';
              if (it.dataset.label === 'runs') return it.raw.model;
              if (it.dataset.label === 'mean') {
                return byTime ? (prepared.table[it.dataIndex]?.model ?? '') : it.label;
              }
              return it.label ?? '';
            },
            label: (c) => {
              if (c.dataset.label === 'runs') {
                return `run ${c.raw.run} ${c.raw.bound}: ${c.raw.y.toFixed(1)}%`;
              }
              // Trend points are {x, y}, not the bar's [lo, hi] pair.
              if (c.dataset.type === 'line') return `${c.dataset.label}: ${c.raw.y.toFixed(1)}%`;
              return `mean ${c.raw[0].toFixed(1)}% - ${c.raw[1].toFixed(1)}%`;
            },
            afterLabel: (c) => {
              if (c.dataset.label !== 'mean') return '';
              const r = prepared.table[c.dataIndex];
              return r && r.released ? `released ${r.released}` : '';
            },
          },
          titleFont: { family: mono }, bodyFont: { family: mono },
        },
      },
      scales: {
        x: {
          display: !byTime,
          ticks: { color: '#8b949e', font: { size: 10, family: mono },
                   autoSkip: false, maxRotation: 90, minRotation: 90 },
          grid: { color: '#161b22' },
        },
        // Real elapsed time. This is what makes the least-squares line render as a
        // straight line -- on the category axis the same fit bends, because equal
        // column widths misrepresent unequal gaps between releases. Plain linear
        // rather than Chart.js's time scale, which would need a date adapter the
        // page deliberately doesn't load.
        xTime: {
          type: 'linear',
          display: byTime,
          offset: false,
          min: prepared.xRange?.min,
          max: prepared.xRange?.max,
          ticks: {
            color: '#8b949e', font: { size: 10, family: mono },
            maxRotation: 45, minRotation: 45, autoSkip: true, maxTicksLimit: 14,
            callback: (v) => {
              const d = new Date(v);
              return `${MONTH_NAMES[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`;
            },
          },
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
      <td class="dim">${esc(r.released || '--')}</td>
      <td class="num">${(r.lower * 100).toFixed(1)}%</td>
      <td class="num">${(r.upper * 100).toFixed(1)}%</td>
      <td class="num dim">${r.validRuns}</td>
    </tr>`).join('');
  return `<div class="results-table">
    <table>
      <thead><tr><th>Model</th><th>Family</th><th>Released</th>
        <th>Lower</th><th>Upper</th><th>Runs</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

function sortBarHtml(sortMode, haveDates) {
  const chip = (mode, text, title) =>
    `<button class="schip${sortMode === mode ? ' on' : ''}" data-sort="${mode}"
       ${haveDates ? '' : 'disabled'} title="${esc(title)}">${esc(text)}</button>`;
  return `<div class="sortbar"><span class="sortlabel">sort</span>
    ${chip('rank', 'by self-report', 'Highest self-reported probability first')}
    ${chip('date', 'by release date', haveDates
      ? 'Oldest model first, with a fitted trend for each bound'
      : 'No release dates available for this dataset')}</div>`;
}

// The numbers behind the dashed lines. A trend nobody can read the slope of is
// decoration; the slope and R-squared are the actual finding.
function trendNoteHtml(p) {
  if (p.sortMode !== 'date') return '';
  if (!p.trend) {
    return `<p class="failed-note">Not enough dated models here to fit a trend.</p>`;
  }
  const t = p.trend;
  const sign = (v) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}`;
  const dropped = p.undated
    ? ` &middot; ${p.undated} model${p.undated > 1 ? 's' : ''} omitted for having no
        catalogue release date (delisted from OpenRouter); they are not guessed at.`
    : '';
  // A dashed line drawn across a chart reads as "there is a trend" whatever the
  // fit quality, so say plainly when there isn't one. R-squared here is the share
  // of variation release date accounts for -- near zero means the slope is noise.
  const weak = Math.max(t.lower.r2, t.upper.r2) < 0.1
    ? ` <strong>Both fits are essentially flat:</strong> release date accounts for
        almost none of the variation between models, so read the dashed lines as
        <em>no trend</em> rather than a shallow one. What a model reports is
        dominated by which lab built it, not by when it shipped.`
    : '';
  // Filtering to one family can leave three or four points, where a single model
  // swings both slope and R-squared. Say so rather than letting the reader treat
  // a two-decimal R-squared over four points as if it meant something.
  const small = t.n < 6
    ? ` <strong>Only ${t.n} models</strong> &mdash; one release moves both the slope
        and the fit substantially, so treat this as indicative, not established.`
    : '';
  return `<p class="trend-note">
    <strong>Trend</strong> over ${t.n} models, ${esc(t.from)} to ${esc(t.to)} &mdash;
    upper bound <strong>${sign(t.upper.slope)} pts/year</strong> (R&sup2; ${t.upper.r2.toFixed(2)}),
    lower bound <strong>${sign(t.lower.slope)} pts/year</strong> (R&sup2; ${t.lower.r2.toFixed(2)}).${weak}${small}
    Fitted against elapsed time, not rank. Dates are OpenRouter listing dates, which
    trail vendor announcements by days.${dropped}</p>`;
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
  const dates = await loadModelDates();
  const haveDates = Object.keys(data.models || {}).some((k) => dates[k]);
  let active = null;        // null = every family; otherwise a Set of family names
  let sortMode = 'rank';    // 'rank' is the published default and stays that way
  let chart = null;
  let justOpen = false;     // survives a filter redraw

  // From "everything on", the first click solos that family -- otherwise isolating
  // one of thirteen means twelve clicks. After that it's additive. Emptying the
  // set falls back to "everything" rather than an empty chart.
  function toggleFamily(fam) {
    if (active === null) { active = new Set([fam]); return; }
    if (active.has(fam)) active.delete(fam); else active.add(fam);
    if (active.size === 0) active = null;
  }

  function render() {
    const p = prepare(data, active, sortMode, dates);
    const failedNote = p.failed.length
      ? `<p class="failed-note">Not charted (0 valid runs): ${p.failed.map(esc).join(', ')}</p>` : '';
    const shown = (active || p.undated)
      ? `${p.charted} of ${p.total} models` : `${p.charted} models`;

    if (chart) { chart.destroy(); chart = null; }
    section.innerHTML = `
      <h2>${esc(cfg.title)}</h2>
      <p class="section-subtitle">"${esc(cfg.question)}" &mdash; ${p.runsPerModel} runs per model, averaged
        &middot; ${shown} &middot; ${esc(p.timestamp)}</p>
      ${filterBarHtml(data, active)}
      ${sortBarHtml(sortMode, haveDates)}
      <div class="chart-scroll"><div class="chart-container"><canvas id="canvas-${id}"></canvas></div></div>
      ${trendNoteHtml(p)}
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
    section.querySelectorAll('.schip[data-sort]').forEach((btn) => {
      btn.addEventListener('click', () => { sortMode = btn.dataset.sort; render(); });
    });

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
