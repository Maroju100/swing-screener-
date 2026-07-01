const list = document.getElementById("screener-list");
const panel = document.getElementById("main-panel");

async function loadScreener() {
  const res = await fetch("/api/screener");
  const stocks = await res.json();
  list.innerHTML = "";
  stocks.forEach((s) => {
    const up = s.change >= 0;
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
          <div class="price">$${s.price.toFixed(2)}</div>
          <div class="change ${up ? "up" : "down"}">
            ${up ? "▲" : "▼"} ${Math.abs(s.change).toFixed(2)} (${Math.abs(s.change_pct).toFixed(2)}%)
          </div>
        </div>
      </div>
      <div class="card-signal">⚡ ${s.signal}</div>
    `;
    card.addEventListener("click", () => showDetails(s.symbol, card));
    list.appendChild(card);
  });
}

async function showDetails(symbol, cardEl) {
  // Highlight active card
  document.querySelectorAll(".stock-card").forEach((c) => c.classList.remove("active"));
  cardEl.classList.add("active");

  panel.innerHTML = `<div class="loading">Loading details for ${symbol}…</div>`;

  const res = await fetch(`/api/details/${symbol}`);
  if (!res.ok) {
    panel.innerHTML = `<div class="loading">Failed to load details.</div>`;
    return;
  }
  const d = await res.json();
  const up = d.change >= 0;

  panel.innerHTML = `
    <!-- Header -->
    <div class="details-header">
      <div class="details-title">
        <div class="symbol">${d.symbol}</div>
        <div class="company">${d.name}</div>
        <div class="sector-badge">${d.sector}</div>
      </div>
      <div class="price-block">
        <div class="big-price">$${d.price.toFixed(2)}</div>
        <div class="price-change ${up ? "up" : "down"}">
          ${up ? "▲" : "▼"} $${Math.abs(d.change).toFixed(2)} (${Math.abs(d.change_pct).toFixed(2)}%)
        </div>
      </div>
    </div>

    <!-- Signal banner -->
    <div class="signal-banner">
      <div>⚡</div>
      <div>
        <span class="signal-label">${d.signal}</span>
        <span class="signal-analysis"> — ${d.analysis}</span>
      </div>
    </div>

    <!-- Sparkline chart -->
    <div class="chart-section">
      <div class="section-title">Price History (9-day)</div>
      <div class="chart-container">
        ${buildSparkline(d.chart_data, up)}
      </div>
    </div>

    <!-- Metrics grid -->
    <div class="metrics-grid">
      ${metric("Volume", formatVol(d.volume), `Avg ${formatVol(d.avg_volume)}`)}
      ${metric("Market Cap", d.market_cap)}
      ${metric("P/E Ratio", d.pe_ratio.toFixed(1))}
      ${metric("EPS", `$${d.eps.toFixed(2)}`)}
      ${metric("52-Week High", `$${d.week_52_high.toFixed(2)}`)}
      ${metric("52-Week Low", `$${d.week_52_low.toFixed(2)}`)}
      ${metric("Beta", d.beta.toFixed(2))}
      ${metric("Dividend Yield", d.dividend_yield)}
      ${rsiMetric(d.rsi)}
      ${smaMetric(d.price, d.sma_50, d.sma_200)}
    </div>

    <!-- Company description -->
    <div class="description-section">
      <div class="section-title">About</div>
      <p>${d.description}</p>
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
  const color = rsi > 70 ? "var(--red)" : rsi < 30 ? "var(--green)" : "var(--accent)";
  return `
    <div class="metric-card">
      <div class="metric-label">RSI (14)</div>
      <div class="metric-value" style="color:${color}">${rsi.toFixed(1)}</div>
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

function smaMetric(price, sma50, sma200) {
  const a50 = price > sma50 ? "up" : "down";
  const a200 = price > sma200 ? "up" : "down";
  return `
    <div class="metric-card">
      <div class="metric-label">Moving Averages</div>
      <div class="sma-compare">
        <div class="sma-item"><span class="${a50}">50-day</span><br>$${sma50.toFixed(2)}</div>
        <div class="sma-item"><span class="${a200}">200-day</span><br>$${sma200.toFixed(2)}</div>
      </div>
    </div>
  `;
}

function formatVol(v) {
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + "M";
  if (v >= 1_000) return (v / 1_000).toFixed(0) + "K";
  return v.toString();
}

function buildSparkline(data, up) {
  if (!data || data.length < 2) return "";
  const min = Math.min(...data);
  const max = Math.max(...data);
  const pad = (max - min) * 0.1 || 1;
  const lo = min - pad;
  const hi = max + pad;
  const W = 100;
  const H = 100;
  const step = W / (data.length - 1);
  const points = data.map((v, i) => {
    const x = i * step;
    const y = H - ((v - lo) / (hi - lo)) * H;
    return `${x},${y}`;
  });
  const color = up ? "var(--green)" : "var(--red)";
  const areaBottom = `${W},${H} 0,${H}`;
  return `
    <svg class="sparkline" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${color}" stop-opacity="0.25"/>
          <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
        </linearGradient>
      </defs>
      <polygon points="${points.join(" ")} ${areaBottom}" fill="url(#sg)"/>
      <polyline points="${points.join(" ")}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>
  `;
}

loadScreener();
