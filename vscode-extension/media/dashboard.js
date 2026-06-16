/* global Chart, GridStack, acquireVsCodeApi */
(function () {
  "use strict";
  const vscode = acquireVsCodeApi();
  let modelChart = null;
  let secondChart = null;
  let grid = null;
  let saveTimer = null;
  const loaded = new Set(); // sessionIds whose prompts were requested
  const promptStore = new Map(); // sessionId -> items
  const sessionModel = new Map(); // sessionId -> model hint for tokenizer

  const DEFAULT_LAYOUT = [
    { id: "overview", x: 0, y: 0, w: 12, h: 2 },
    { id: "modelChart", x: 0, y: 2, w: 6, h: 4 },
    { id: "secondChart", x: 6, y: 2, w: 6, h: 4 },
    { id: "sessions", x: 0, y: 6, w: 7, h: 5 },
    { id: "tokenizer", x: 7, y: 6, w: 5, h: 5 },
  ];

  const $ = (id) => document.getElementById(id);
  const cssVar = (n, f) => getComputedStyle(document.body).getPropertyValue(n).trim() || f;
  function palette(n) {
    const base = [
      "--vscode-charts-blue",
      "--vscode-charts-green",
      "--vscode-charts-orange",
      "--vscode-charts-purple",
      "--vscode-charts-red",
      "--vscode-charts-yellow",
    ];
    const out = [];
    for (let i = 0; i < n; i++) out.push(cssVar(base[i % base.length], "#888"));
    return out;
  }
  function humanTokens(v) {
    v = Number(v) || 0;
    if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
    if (v >= 1e3) return (v / 1e3).toFixed(1) + "k";
    return String(Math.round(v));
  }
  function money(v) {
    v = Number(v) || 0;
    if (v > 0 && Math.abs(v) < 1) return "$" + v.toFixed(4);
    return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  const shortModel = (m) => String(m || "unknown").replace("claude-", "").slice(0, 22);

  // ---- gridstack ----
  function initGrid() {
    if (!window.GridStack) return;
    grid = GridStack.init({
      cellHeight: 70,
      margin: 7,
      float: true,
      handle: ".gs-drag",
      resizable: { handles: "se" },
    });
    grid.on("change", () => {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        vscode.postMessage({ type: "saveLayout", grid: grid.save(false) });
      }, 400);
    });
    grid.on("resizestop", () => {
      if (modelChart) modelChart.resize();
      if (secondChart) secondChart.resize();
    });
  }
  function applyLayout(saved) {
    if (!grid || !Array.isArray(saved)) return;
    try {
      grid.load(saved, false);
    } catch (e) {
      /* ignore malformed layout */
    }
  }

  // ---- buttons ----
  document.querySelectorAll("button[data-cmd]").forEach((b) => {
    b.addEventListener("click", () => {
      const cmd = b.getAttribute("data-cmd");
      if (cmd === "refresh") vscode.postMessage({ type: "refresh" });
      else vscode.postMessage({ type: "runCommand", command: cmd });
    });
  });
  $("resetLayout").addEventListener("click", () => {
    applyLayout(DEFAULT_LAYOUT);
    vscode.postMessage({ type: "saveLayout", grid: DEFAULT_LAYOUT });
  });
  $("tokRun").addEventListener("click", () => {
    vscode.postMessage({ type: "tokenize", text: $("tokInput").value, model: $("tokModel").value });
  });

  // ---- cards / charts ----
  function card(k, v, sub) {
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = '<div class="k"></div><div class="v"></div><div class="sub"></div>';
    el.querySelector(".k").textContent = k;
    el.querySelector(".v").textContent = v;
    el.querySelector(".sub").textContent = sub || "";
    return el;
  }
  function baseChartOpts() {
    Chart.defaults.color = cssVar("--vscode-foreground", "#ccc");
    Chart.defaults.borderColor = cssVar("--vscode-panel-border", "#8884");
    Chart.defaults.font.family = cssVar("--vscode-font-family", "sans-serif");
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false } },
        y: { beginAtZero: true, grid: { color: cssVar("--vscode-panel-border", "#8884") } },
      },
    };
  }
  function drawBar(canvasId, labels, data, existing, label) {
    if (existing) existing.destroy();
    return new Chart($(canvasId).getContext("2d"), {
      type: "bar",
      data: { labels, datasets: [{ label: label || "", data, backgroundColor: palette(labels.length), borderRadius: 4 }] },
      options: baseChartOpts(),
    });
  }
  function drawLine(canvasId, labels, data, existing, label) {
    if (existing) existing.destroy();
    const color = cssVar("--vscode-charts-blue", "#539bf5");
    return new Chart($(canvasId).getContext("2d"), {
      type: "line",
      data: { labels, datasets: [{ label: label || "", data, borderColor: color, backgroundColor: color + "33", fill: true, tension: 0.25, pointRadius: 2 }] },
      options: baseChartOpts(),
    });
  }

  // ---- snapshot ----
  function aggLiveModels(live) {
    const m = {};
    for (const s of live.sessions) {
      for (const ln of s.models) {
        const a = (m[ln.model] = m[ln.model] || { tokens: 0, cost: 0 });
        a.tokens += ln.tokens;
        a.cost += ln.cost;
      }
    }
    return m;
  }

  function renderSnapshot(s) {
    const badge = $("modeBadge");
    badge.className = "badge " + (s.mode === "empty" ? "" : s.mode === "claude" ? "claude" : s.mode);
    badge.textContent =
      s.mode === "live"
        ? "● Live OTel"
        : s.mode === "billing"
          ? "Imported CSV"
          : s.mode === "claude"
            ? "● Claude Code"
            : "No data";
    $("subline").textContent =
      "source: " + s.source + " · scope: " + s.scope + " · updated " + new Date(s.generatedAt).toLocaleTimeString();

    const ov = $("overview");
    ov.innerHTML = "";
    $("sessionsHint").textContent = "";

    if (s.mode === "claude" && s.claude) {
      const c = s.claude;
      ov.appendChild(card("Tokens", humanTokens(c.totalTokens), "scope: " + s.scope));
      ov.appendChild(card("Cost", (c.costEstimated ? "~" : "") + money(c.totalCost), c.costEstimated ? "rate-estimated" : "logged"));
      ov.appendChild(card("Sessions", String(c.sessionCount), c.currentSessionId ? "current matched" : ""));
      const rows = Object.entries(c.modelTotals).sort((a, b) => b[1].tokens - a[1].tokens);
      modelChart = drawBar("modelChart", rows.map((r) => shortModel(r[0])), rows.map((r) => r[1].tokens), modelChart, "tokens");
      const top = c.sessions.slice(0, 8);
      $("secondChartTitle").textContent = "By session (tokens)";
      secondChart = drawBar("secondChart", top.map((x) => x.shortId), top.map((x) => x.tokens), secondChart, "tokens");
      $("sessionsHint").textContent = "(click a session → prompts → tokenize)";
      for (const ss of c.sessions) sessionModel.set(ss.id, (ss.models[0] || {}).model || "claude");
      renderSessions(c.sessions.slice(0, 8), true);
    } else if (s.mode === "live") {
      ov.appendChild(card("Tokens", humanTokens(s.live.totalTokens), "scope: " + s.scope));
      ov.appendChild(card("Est. cost", "~" + money(s.live.totalCost), "estimated from token rates"));
      ov.appendChild(card("Sessions", String(s.live.sessionCount), "live OTel"));
      const agg = aggLiveModels(s.live);
      const rows = Object.entries(agg).sort((a, b) => b[1].tokens - a[1].tokens);
      modelChart = drawBar("modelChart", rows.map((r) => shortModel(r[0])), rows.map((r) => r[1].tokens), modelChart, "tokens");
      const top = s.live.sessions.slice(0, 8);
      $("secondChartTitle").textContent = "By session (tokens)";
      secondChart = drawBar("secondChart", top.map((x) => x.shortId), top.map((x) => x.tokens), secondChart, "tokens");
      const hasContent = !!s.live.contentAvailable;
      $("sessionsHint").textContent = hasContent
        ? "(OTel · captured prompt content → tokenize)"
        : "(OTel · token counts, no prompt text)";
      for (const ss of s.live.sessions) sessionModel.set(ss.id, (ss.models[0] || {}).model || "gpt-4.1");
      renderSessions(s.live.sessions.slice(0, 6), hasContent);
    } else if (s.mode === "billing" && s.billing.report) {
      const t = s.billing.report.total;
      ov.appendChild(card("Billed", money(t.net), "after included-quota discount"));
      ov.appendChild(card("Gross", money(t.gross), "before discount"));
      ov.appendChild(card("Requests", humanTokens(t.qty), humanTokens(t.billed_qty) + " billed"));
      ov.appendChild(card("Models", String(Object.keys(s.billing.report.models).length), s.billing.csvName || ""));
      const rows = Object.entries(s.billing.report.models).sort((a, b) => b[1].net - a[1].net);
      modelChart = drawBar("modelChart", rows.map((r) => r[0].slice(0, 22)), rows.map((r) => r[1].net), modelChart, "net $");
      const days = Object.keys(s.billing.report.daily).filter((d) => d !== "?").sort();
      $("secondChartTitle").textContent = "Daily net $";
      secondChart = drawLine("secondChart", days, days.map((d) => s.billing.report.daily[d].net), secondChart, "net $");
      renderSessions([], false);
    } else {
      ov.appendChild(card("No data", "—", "Import a CSV, start OTel, or switch source to claude"));
      if (modelChart) (modelChart.destroy(), (modelChart = null));
      if (secondChart) (secondChart.destroy(), (secondChart = null));
      renderSessions([], false);
    }

    if (s.apiUsage) {
      const a = s.apiUsage;
      const t = card(
        "API spend · " + a.period,
        money(a.copilotNet) + " copilot",
        "total " + money(a.totalNet) + " · " + a.scope + " · aggregate, no model detail",
      );
      t.style.borderStyle = "dashed";
      ov.appendChild(t);
    }
  }

  function renderSessions(sessions, withPrompts) {
    const root = $("sessions");
    root.innerHTML = "";
    if (!sessions.length) {
      root.innerHTML = '<div class="hint">No sessions to show.</div>';
      return;
    }
    for (const ss of sessions) {
      const d = document.createElement("details");
      d.className = "session";
      d.dataset.sid = ss.id;
      const when = ss.lastIso ? new Date(ss.lastIso).toLocaleString() : "—";
      const sum = document.createElement("summary");
      sum.innerHTML = '<span class="sid"></span><span class="nums"></span>';
      sum.querySelector(".sid").textContent =
        ss.shortId + (ss.isCurrent ? " ◀ current" : "") + "  ·  " + when;
      sum.querySelector(".nums").textContent =
        humanTokens(ss.tokens) + " tok  ·  " + (ss.costEstimated ? "~" : "") + money(ss.cost);
      d.appendChild(sum);

      const mwrap = document.createElement("div");
      mwrap.className = "models";
      for (const ln of ss.models || []) {
        const row = document.createElement("div");
        const l = document.createElement("span");
        l.textContent = shortModel(ln.model);
        const r = document.createElement("span");
        r.textContent =
          humanTokens(ln.tokens) + " tok  ·  in " + humanTokens(ln.in) + " / out " + humanTokens(ln.out);
        row.appendChild(l);
        row.appendChild(r);
        mwrap.appendChild(row);
      }
      d.appendChild(mwrap);

      if (withPrompts) {
        const pc = document.createElement("div");
        pc.className = "prompts";
        pc.dataset.prompts = ss.id;
        pc.innerHTML = '<div class="hint">expand to load prompts…</div>';
        d.appendChild(pc);
        d.addEventListener("toggle", () => {
          if (d.open && !loaded.has(ss.id)) {
            loaded.add(ss.id);
            pc.innerHTML = '<div class="hint">loading prompts…</div>';
            vscode.postMessage({ type: "requestPrompts", sessionId: ss.id });
          }
        });
      }
      root.appendChild(d);
    }
  }

  function renderPrompts(sessionId, items) {
    promptStore.set(sessionId, items);
    const pc = document.querySelector('[data-prompts="' + cssEscape(sessionId) + '"]');
    if (!pc) return;
    pc.innerHTML = "";
    if (!items.length) {
      pc.innerHTML = '<div class="hint">no user prompts captured in this session.</div>';
      return;
    }
    items.forEach((p, i) => {
      const row = document.createElement("div");
      row.className = "prompt";
      const head = document.createElement("div");
      head.className = "prompt-head";
      const meta = document.createElement("span");
      meta.className = "prompt-meta";
      meta.textContent = "#" + (i + 1) + " · " + p.tokenCount + " tok · " + p.chars + " chars";
      const btn = document.createElement("button");
      btn.className = "ghost tiny";
      btn.textContent = "Tokenize ▸";
      btn.addEventListener("click", () => {
        $("tokModel").value = sessionModel.get(sessionId) || "claude";
        $("tokInput").value = p.text;
        vscode.postMessage({ type: "tokenize", text: p.text, model: $("tokModel").value });
        $("tokInput").scrollIntoView({ behavior: "smooth", block: "center" });
      });
      head.appendChild(meta);
      head.appendChild(btn);
      const body = document.createElement("div");
      body.className = "prompt-text";
      body.textContent = p.text.length > 240 ? p.text.slice(0, 240) + "…" : p.text;
      row.appendChild(head);
      row.appendChild(body);
      pc.appendChild(row);
    });
  }

  function cssEscape(s) {
    return String(s).replace(/["\\]/g, "\\$&");
  }

  // ---- tokenizer ----
  function renderTokens(r) {
    $("tokMeta").innerHTML =
      "<b>" + r.count + "</b> tokens · <b>" + r.chars + "</b> chars · <b>" + r.bytes +
      "</b> bytes · encoder <b>" + r.encoder + "</b> · model <b>" + r.model + "</b>";
    const out = $("tokOut");
    out.innerHTML = "";
    r.tokens.forEach((t, i) => {
      const span = document.createElement("span");
      const ws = t.text.trim() === "";
      span.className = "tok" + (ws ? " ws" : "");
      span.style.background = "hsla(" + ((i * 53) % 360) + ", 70%, 50%, 0.22)";
      span.title = "#" + i + " · id " + t.id + (t.merged && t.merged > 1 ? " · " + t.merged + " tokens" : "");
      span.textContent = t.text === "" ? "·" : t.text;
      out.appendChild(span);
    });
    $("tokNote").textContent = r.note || "";
  }

  // ---- inbound ----
  window.addEventListener("message", (e) => {
    const m = e.data;
    if (m.type === "snapshot") renderSnapshot(m.payload);
    else if (m.type === "tokenized") renderTokens(m.payload);
    else if (m.type === "prompts") renderPrompts(m.sessionId, m.items);
    else if (m.type === "layout") applyLayout(m.grid);
    else if (m.type === "error") $("subline").textContent = "⚠ " + m.message;
  });

  initGrid();
  vscode.postMessage({ type: "ready" });
})();
