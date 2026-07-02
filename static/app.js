const list = document.getElementById("screener-list");
const panel = document.getElementById("main-panel");
const metaBar = document.getElementById("meta-bar");

async function loadScreener() {
  list.innerHTML = `<div class="loading">Loading live scan…</div>`;
  const res = await fetch("/api/screener");
  const { stocks, meta, last_updated } = await res.json();

  // Meta bar
  if (meta && meta.scan_title) {
    const ts = last_updated
      ? new Date(last_updated * 1000).toLocaleTimeString()
      : "unknown";
    metaBar.innerHTML =
      `<span class="meta-title">${meta.scan_title}</span>` +
      `<span class="meta-count">${meta.total_items ?? stocks.length} matches</span>` +
      `<span class="meta-time">Updated ${ts}</span>`;
  }

  list.innerHTML = "";
  stocks.forEach((s) => {
    const up = s.change_pct >= 0;
    const card = document.createElement("div");
    card.className = "stock-card";
    card.dataset.symbol = s.symbol;
    card.innerHTML = `
      <div class="card-top">
        <div class="card-left">
          <div class="symbol">${s.symbol}</div>
          <div class="name">${s.name}</div>
        </div>
        <div class="card-right">
          <div class="price">$${Number(s.price).toFixed(2)}</div>
          <div class="change ${up ? "up" : "down"}">
            ${up ? "▲" : "▼"} ${Math.abs(s.change_pct).toFixed(2)}%
          </div>
        </div>
      </div>
      <div class="card-signal">⚡ ${s.signal}</div>
    `;
    card.addEventListener("click", () => showDetails(s, card));
    list.appendChild(card);
  });
}

async function showDetails(s, cardEl) {
  document.querySelectorAll(".stock-card").forEach((c) => c.classList.remove("active"));
  cardEl.classList.add("active");

  const up = s.change_pct >= 0;
  const rsiColor = s.rsi > 65 ? "var(--red)" : s.rsi < 35 ? "var(--green)" : "var(--accent)";

  panel.innerHTML = `
    <!-- Header -->
    <div class="details-header">
      <div class="details-title">
        <div class="symbol">${s.symbol}</div>
        <div class="company">${s.name}</div>
        ${s.sector ? `<div class="sector-badge">${s.sector}</div>` : ""}
      </div>
      <div class="price-block">
        <div class="big-price">$${Number(s.price).toFixed(2)}</div>
        <div class="price-change ${up ? "up" : "down"}">
          ${up ? "▲" : "▼"} $${Math.abs(s.change).toFixed(2)} (${Math.abs(s.change_pct).toFixed(2)}%)
        </div>
      </div>
    </div>

    <!-- Signal banner -->
    <div class="signal-banner">
      <div>⚡</div>
      <div>
        <span class="signal-label">${s.signal}</span>
        <span class="signal-analysis"> — RSI ${s.rsi.toFixed(1)} · Relative volume ${s.relative_volume.toFixed(2)}x · ${s.market_cap}</span>
      </div>
    </div>

    <!-- Metrics grid -->
    <div class="metrics-grid">
      ${metric("Volume", formatVol(s.volume), `${s.relative_volume.toFixed(2)}x avg`)}
      ${metric("Market Cap", s.market_cap)}
      ${rsiMetric(s.rsi)}
      ${metric("Price", `$${Number(s.price).toFixed(2)}`)}
      ${metric("Change", `${up ? "+" : ""}${s.change_pct.toFixed(2)}%`, `$${up ? "+" : ""}${s.change.toFixed(2)}`)}
    </div>

    <!-- Scan filters badge -->
    <div class="scan-info">
      <div class="section-title">Live from Robinhood Scan</div>
      <div class="filter-chips">
        <span class="chip">RSI 30–65</span>
        <span class="chip">Rel Vol ≥ 1×</span>
        <span class="chip">Mkt Cap ≥ $1B</span>
        <span class="chip">Price $10–$300</span>
        <span class="chip">Stocks only</span>
      </div>
    </div>
  `;
}

function metric(label, value, sub = "") {
  return `
    <div class="metric-card">
      <div class="metric-label">${label}</div>
      <div class="metric-value">${value}</div>
      ${sub ? `<div class="metric-sub">${sub}</div>` : ""}
    </div>
  `;
}

function rsiMetric(rsi) {
  const pct = Math.min(Math.max(rsi, 0), 100);
  const color = rsi > 65 ? "var(--red)" : rsi < 35 ? "var(--green)" : "var(--accent)";
  const label = rsi < 35 ? "Oversold" : rsi > 65 ? "Overbought" : "Neutral";
  return `
    <div class="metric-card">
      <div class="metric-label">RSI (14-day)</div>
      <div class="metric-value" style="color:${color}">${rsi.toFixed(1)}</div>
      <div class="metric-sub">${label}</div>
      <div class="rsi-bar-wrap">
        <div class="rsi-track">
          <div class="rsi-fill" style="width:${pct}%; background:${color}">
            <div class="rsi-marker" style="left:100%; border-color:${color}"></div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function formatVol(v) {
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + "M";
  if (v >= 1_000) return (v / 1_000).toFixed(0) + "K";
  return v.toString();
}

loadScreener();
