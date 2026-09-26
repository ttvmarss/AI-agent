/* research.js — the live research workspace (renderer only).
 *
 * Every visual change here is the result of a "research_event" from the
 * backend (mentis_research/events.py). There are no demo timers and no
 * invented data: a card exists only because a real result was discovered,
 * a fact appears only because inspection fetched it.
 *
 * The one thing this file adds is PACING: events are applied in their exact
 * order, with a short per-type dwell so fast bursts (ten results parsed in
 * 40 ms) stay legible as a sequence. The dwell shrinks automatically as the
 * backlog grows, so the view never falls meaningfully behind reality.
 *
 * Layout is a function of state: each card belongs to a zone (incoming,
 * focus, useful, evidence, set-aside, tucked-behind-artifact, receded) and
 * the layout engine assigns it a transform. CSS transitions carry it there
 * and retarget mid-flight, so interrupted motion adapts instead of queueing.
 *
 * Integrates with the existing app: reuses window.__jarvisSocket (socket.js)
 * and the page's CSS tokens; touches the orb only through a body class.
 */

(function () {
  "use strict";

  // --------------------------------------------------------------- pacing
  const DWELL = {
    "task.started": 650,
    "research.session.started": 720,
    "research.query.started": 160,
    "research.result.discovered": 150,
    "research.source.queued": 40,
    "research.source.inspecting": 520,
    "research.source.metadata_updated": 300,
    "research.source.verifying": 420,
    "research.source.useful": 420,
    "research.source.selected": 620,
    "research.source.rejected": 170,
    "research.source.failed": 260,
    "stage.changed": 420,
    "research.artifact.creating": 950,
    "research.artifact.created": 1100,
    "benchmark.started": 700,
    "benchmark.result": 110,
    "response.ready": 500,
  };

  const S = {
    sid: null,
    title: "",
    stage: "idle",
    opened: false,
    settled: false,
    collapsed: false,
    paused: false,
    finished: false,
    percent: 0,
    counts: {},
    cards: new Map(), // source_id -> card model
    arrival: 0,
    artifacts: [], // {art, el, h}
    forming: null, // {source_ids}
    evalp: null, // {el, rows:Map, criteria, host, comparison}
    answer: null,
    lastSeq: 0,
    viewer: { open: false, id: null, tab: "facts", detail: null, mode: "source" },
  };

  // ------------------------------------------------------------------ DOM
  const $ = (sel, root) => (root || document).querySelector(sel);
  function h(tag, cls, html) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (html != null) el.innerHTML = html;
    return el;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function fmtNum(n) {
    if (n == null || isNaN(n)) return null;
    n = Number(n);
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k";
    return String(n);
  }
  function hhmmss(ts) {
    try { return new Date(ts * 1000).toTimeString().slice(0, 8); } catch (e) { return ""; }
  }
  function tf(x, y, s) {
    return `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0) scale(${s == null ? 1 : s})`;
  }

  let R = null; // root refs
  function ensureRoot() {
    if (R) return R;
    const root = h("div");
    root.id = "rx-root";
    root.innerHTML = `
      <svg id="rx-links"><defs>
        <linearGradient id="rx-beam-grad" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stop-color="#4fd8e8" stop-opacity="0"/>
          <stop offset="1" stop-color="#4fd8e8" stop-opacity="0.8"/>
        </linearGradient></defs>
        <path class="beam" d=""/><path class="link" d=""/></svg>
      <div id="rx-stage"></div>
      <div id="rx-feed"><h4>&#9670; LIVE ACTIVITY</h4><div class="rx-feed-list"></div></div>
      <div id="rx-header" class="rx-hit">
        <div class="rx-h-row">
          <div class="rx-h-title"></div>
          <span class="rx-h-stage">RESEARCH</span>
          <span class="rx-h-pct">0%</span>
        </div>
        <div class="rx-h-bar"><i></i></div>
        <div class="rx-h-row">
          <div class="rx-h-counts"></div>
          <div class="rx-h-ctl">
            <button class="rx-btn" data-act="pause">Pause</button>
            <button class="rx-btn warn" data-act="stop">Stop</button>
            <button class="rx-btn" data-act="sources">Sources</button>
            <button class="rx-btn" data-act="collapse">Collapse</button>
            <button class="rx-btn" data-act="close" style="display:none">Close</button>
          </div>
        </div>
      </div>
      <div id="rx-task"></div>
      <div class="rx-label" id="rx-l-incoming"></div>
      <div class="rx-label" id="rx-l-focus"></div>
      <div class="rx-label warm" id="rx-l-evidence"></div>
      <div class="rx-label" id="rx-l-aside"></div>
      <div class="rx-more" id="rx-more-incoming"></div>
      <div class="rx-more" id="rx-more-aside"></div>
      <div id="rx-answer"></div>
      <div id="rx-dock"></div>
      <div id="rx-viewer">
        <div class="rx-v-head"><div class="rx-v-title"></div><div class="rx-v-url"></div><div class="rx-v-sub"></div></div>
        <div class="rx-v-actions"></div>
        <div class="rx-v-tabs"></div>
        <div class="rx-v-body"></div>
        <div class="rx-v-follow"><input type="text" placeholder="Ask a follow-up about this source…"/><button class="rx-btn" data-act="follow">Ask</button></div>
      </div>`;
    document.body.appendChild(root);
    const pulse = h("div");
    pulse.id = "rx-core-pulse";
    document.body.appendChild(pulse);
    R = {
      root,
      pulse,
      links: $("#rx-links", root),
      beam: $("#rx-links .beam", root),
      link: $("#rx-links .link", root),
      stage: $("#rx-stage", root),
      feed: $("#rx-feed", root),
      feedList: $(".rx-feed-list", root),
      header: $("#rx-header", root),
      hTitle: $(".rx-h-title", root),
      hStage: $(".rx-h-stage", root),
      hPct: $(".rx-h-pct", root),
      hBar: $(".rx-h-bar i", root),
      hCounts: $(".rx-h-counts", root),
      task: $("#rx-task", root),
      lIncoming: $("#rx-l-incoming", root),
      lFocus: $("#rx-l-focus", root),
      lEvidence: $("#rx-l-evidence", root),
      lAside: $("#rx-l-aside", root),
      moreIncoming: $("#rx-more-incoming", root),
      moreAside: $("#rx-more-aside", root),
      answer: $("#rx-answer", root),
      dock: $("#rx-dock", root),
      viewer: $("#rx-viewer", root),
    };
    R.header.addEventListener("click", onHeaderClick);
    R.moreIncoming.addEventListener("click", () => openSourceList("incoming"));
    R.moreAside.addEventListener("click", () => openSourceList("aside"));
    R.viewer.addEventListener("click", onViewerClick);
    $("input", R.viewer).addEventListener("keydown", (e) => {
      e.stopPropagation(); // keep the app's "C" chat hotkey from firing while typing
      if (e.key === "Enter") sendFollowup();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && S.viewer.open) closeViewer();
    });
    return R;
  }

  // ----------------------------------------------------------- geometry
  function orbCenter() {
    const vw = innerWidth, vh = innerHeight;
    const b = document.body.classList;
    if (!b.contains("rx-active") || b.contains("rx-collapsed")) return { x: vw / 2, y: vh / 2 };
    if (b.contains("rx-settled")) return { x: vw / 2 - 0.17 * vw, y: vh / 2 };
    return { x: vw / 2 - 0.26 * vw, y: vh / 2 - 0.02 * vh };
  }

  function geometry() {
    const vw = innerWidth, vh = innerHeight;
    const top = 58, bottom = vh - 66;
    const regionL = Math.round(vw * (S.settled ? 0.5 : 0.36));
    const regionR = vw - 22;
    const gap = 18;
    const cardW = Math.max(210, Math.min(300, Math.floor((regionR - regionL - 2 * gap) / 3)));
    const colA = regionL;
    const colC = regionR - cardW;
    const colB = Math.round((colA + cardW + colC) / 2 - cardW / 2);
    return { vw, vh, top, bottom, regionL, regionR, gap, cardW, colA, colB, colC };
  }

  // ------------------------------------------------------------- cards
  const GLYPH = { github: "GH", web: "WW", docs: "DC", npm: "NP", pypi: "PY", local: "FS" };
  const BADGE = {
    discovered: "DISCOVERED", queued: "QUEUED", inspecting: "INSPECTING", verifying: "VERIFYING",
    useful: "USEFUL", selected: "SELECTED", rejected: "SET ASIDE", failed: "FAILED",
  };

  function chipsFor(src) {
    const m = src.meta || {};
    const out = [];
    const days = m.days_since_update;
    if (m.stars != null) out.push(["★ " + fmtNum(m.stars), ""]);
    if (m.forks != null && m.forks > 0) out.push(["⑂ " + fmtNum(m.forks), ""]);
    if (m.weekly_downloads != null) out.push(["↓ " + fmtNum(m.weekly_downloads) + "/wk", ""]);
    if (m.language) out.push([m.language, ""]);
    if (m.license) out.push([m.license, /GPL/i.test(m.license) ? "warn" : ""]);
    else if (src.source_type === "repository" || src.source_type === "package") out.push(["LICENSE UNKNOWN", "unknown"]);
    if (m.version) out.push(["v" + String(m.version).replace(/^v/, ""), ""]);
    if (days != null) out.push([days === 0 ? "updated today" : `updated ${days}d ago`, days > 365 ? "warn" : ""]);
    if (m.archived) out.push(["ARCHIVED", "warn"]);
    if (m.domain) out.push([m.domain, ""]);
    return out.slice(0, 7);
  }

  function makeCardEl(c) {
    const el = h("div", "rx-card rx-entering");
    el.dataset.id = c.id;
    el.innerHTML = `
      <div class="rx-scan"></div>
      <div class="rx-card-inner">
        <div class="rx-sweep"></div>
        <div class="rx-card-head">
          <div class="rx-ico"></div>
          <div class="rx-card-titles"><div class="rx-card-title"></div><div class="rx-card-sub"></div></div>
          <span class="rx-pin">&#9670;</span>
          <div class="rx-badge"></div>
        </div>
        <div class="rx-card-snippet"></div>
        <div class="rx-chips"></div>
        <div class="rx-facts"></div>
        <div class="rx-card-foot"><span class="rx-time"></span><span class="rx-score"><i></i></span><span class="rx-scoretxt"></span></div>
        <div class="rx-reason"></div>
      </div>`;
    el.addEventListener("click", () => openViewer(c.id));
    c.ref = {
      ico: $(".rx-ico", el), title: $(".rx-card-title", el), sub: $(".rx-card-sub", el), badge: $(".rx-badge", el),
      snippet: $(".rx-card-snippet", el), chips: $(".rx-chips", el), facts: $(".rx-facts", el),
      time: $(".rx-time", el), score: $(".rx-score i", el), scoretxt: $(".rx-scoretxt", el), reason: $(".rx-reason", el),
    };
    c.factEls = new Map();
    const ico = c.ref.ico;
    if (c.src.favicon) {
      const img = new Image();
      img.alt = "";
      img.referrerPolicy = "no-referrer";
      img.onerror = () => { ico.textContent = GLYPH[c.src.provider] || "··"; };
      img.src = c.src.favicon;
      ico.appendChild(img);
    } else {
      ico.textContent = GLYPH[c.src.provider] || "··";
    }
    c.el = el;
    c.dirty = true;
    return el;
  }

  function renderCard(c, changed) {
    if (!c.el) return;
    const src = c.src, r = c.ref;
    c.el.dataset.state = src.state;
    c.el.dataset.provider = src.provider;
    c.el.classList.toggle("pinned", !!(src.meta && src.meta.pinned));
    r.title.textContent = src.title;
    r.sub.textContent = `${(src.provider || "").toUpperCase()} · ${src.source_type || ""}${src.meta && src.meta.owner ? " · " + src.meta.owner : ""}`;
    r.badge.textContent = BADGE[src.state] || String(src.state || "").toUpperCase();
    r.snippet.textContent = src.snippet || "";
    r.chips.innerHTML = chipsFor(src).map(([t, cls]) => `<span class="rx-chip ${cls}">${esc(t)}</span>`).join("");
    // facts: diffed so new information visibly arrives in the existing card
    const changedSet = new Set(changed || []);
    const facts = (src.facts || []).filter((f) => f.label !== "README summary").slice(0, 7);
    const summary = (src.facts || []).find((f) => f.label === "README summary");
    if (summary && summary.value !== c.summaryShown) {
      r.snippet.textContent = summary.value;
      c.summaryShown = summary.value;
    }
    for (const f of facts) {
      let row = c.factEls.get(f.label);
      if (!row) {
        row = h("div", "rx-fact rx-new", `<span class="l"></span><span class="v"></span>`);
        c.factEls.set(f.label, row);
        r.facts.appendChild(row);
        setTimeout(() => row.classList.remove("rx-new"), 600);
      } else if (row.dataset.v !== f.value && changedSet.has(f.label)) {
        row.classList.remove("rx-flash");
        void row.offsetWidth;
        row.classList.add("rx-flash");
      }
      row.dataset.v = f.value;
      row.children[0].textContent = f.label;
      row.children[1].textContent = f.value;
      row.title = `from ${f.origin}`;
    }
    r.time.textContent = src.retrieved_at ? "retrieved " + hhmmss(src.retrieved_at) : "";
    const score = src.relevance == null ? 0 : Math.max(0, Math.min(1, src.relevance));
    r.score.style.transform = `scaleX(${score})`;
    r.scoretxt.textContent = src.relevance == null ? "" : score.toFixed(2);
    const reasons = src.error ? [src.error] : src.reasons || [];
    r.reason.textContent = reasons.slice(0, 2).join(" · ");
  }

  function upsert(src, changed) {
    let c = S.cards.get(src.source_id);
    if (!c) {
      c = { id: src.source_id, src, order: S.arrival++, el: null, h: 0 };
      S.cards.set(src.source_id, c);
    } else {
      c.src = src;
    }
    c.changed = changed;
    c.dirty = true;
    return c;
  }

  // ------------------------------------------------------------- feed
  const FEED_GLYPH = { search: "⌕", result: "+", inspect: "›", verify: "✓", useful: "◆", select: "◆", reject: "−",
    error: "!", artifact: "◈", bench: "≡", control: "‖", info: "·" };
  const feedLines = [];
  function pushFeed(text, kind) {
    ensureRoot();
    const el = h("div", `rx-feed-line ${kind || "info"} fresh`, `<span class="k">${FEED_GLYPH[kind] || "·"}</span>${esc(text)}`);
    el.title = text;
    el.style.transform = "translate3d(0, 19px, 0)";
    el.style.opacity = "0";
    R.feedList.appendChild(el);
    feedLines.unshift(el);
    if (feedLines.length > 9) feedLines.pop().remove();
    requestAnimationFrame(() => {
      feedLines.forEach((line, i) => {
        line.style.transform = `translate3d(0, ${-i * 19}px, 0)`;
        line.style.opacity = String(Math.max(0.15, 1 - i * 0.13));
        if (i > 0) line.classList.remove("fresh");
      });
    });
  }

  // ------------------------------------------------------- artifact UI
  function artifactHTML(art) {
    const conf = art.confidence_metadata || {};
    const rows = (art.findings || []).map((f, i) => `
      <div class="rx-a-row" data-sid="${esc((f.source_ids || [])[0] || "")}" style="animation-delay:${180 + i * 120}ms">
        <span class="rx-a-idx">${String.fromCharCode(65 + i)}</span>
        <div><div class="rx-a-name">${esc(f.title)}</div>
          ${f.detail ? `<div class="rx-a-det">${esc(f.detail)}</div>` : ""}
          ${(f.key_facts || []).length ? `<div class="rx-a-facts">${esc(f.key_facts.slice(0, 4).join(" · "))}</div>` : ""}
        </div>
        <span class="rx-a-score">${f.score != null ? Number(f.score).toFixed(2) : ""}</span>
      </div>`).join("");
    const meta = [
      conf.discovered != null ? `${conf.discovered} DISCOVERED` : "",
      conf.inspected != null ? `${conf.inspected} INSPECTED` : "",
      conf.rejected != null ? `${conf.rejected} SET ASIDE` : "",
      conf.failed ? `${conf.failed} FAILED` : "",
      conf.method ? `METHOD ${String(conf.method).toUpperCase()}` : "",
    ].filter(Boolean).map((t) => `<span>${esc(t)}</span>`).join("");
    return `<div class="rx-a-kicker">&#9670; CONTEXT ARTIFACT · ${esc(art.type)}</div>
      <h3>${esc(art.title)}</h3>
      <div class="rx-a-sum">${esc(art.summary)}</div>
      ${rows || `<div class="rx-a-sum">No sources survived inspection.</div>`}
      <div class="rx-a-meta">${meta}<span>ID ${esc(art.id)}</span></div>`;
  }

  function createArtifact(art) {
    ensureRoot();
    const el = h("div", "rx-artifact rx-forming");
    el.innerHTML = artifactHTML(art);
    el.addEventListener("click", (e) => {
      const row = e.target.closest(".rx-a-row");
      if (row && row.dataset.sid) openViewer(row.dataset.sid);
    });
    // it forms FROM the evidence cluster: start at the cluster's centre
    const g = geometry();
    const ev = [...S.cards.values()].filter((c) => c.src.state === "selected" && c.el);
    let cx = g.colA, cy = g.top + 120;
    if (ev.length) {
      cx = ev.reduce((a, c) => a + c.x, 0) / ev.length;
      cy = ev.reduce((a, c) => a + c.y, 0) / ev.length;
    }
    el.style.transform = tf(cx, cy, 0.35);
    el.style.opacity = "0";
    R.root.appendChild(el);
    const a = { art, el, h: 0, born: performance.now() };
    S.artifacts.push(a);
    void el.offsetWidth;
    el.classList.remove("rx-forming");
    renderDock();
    return a;
  }

  // ------------------------------------------------------- evaluation UI
  const CRIT_LABEL = { license: "License", maintenance: "Maint.", adoption: "Adoption", stack: "Stack", hardware: "Hardware", footprint: "Footprint" };
  function hostLine(host) {
    if (!host) return "";
    const bits = [];
    if (host.ram_gb) bits.push(`${host.ram_gb} GB RAM`);
    bits.push(host.gpu ? `${host.gpu} · ${host.vram_gb} GB VRAM` : "no NVIDIA GPU detected");
    if ((host.languages || []).length) bits.push("stack " + host.languages.join(" + "));
    return "THIS PC · " + bits.join(" · ");
  }
  function createEval(d) {
    ensureRoot();
    const el = h("div", "rx-artifact rx-eval rx-forming");
    const crits = d.criteria || [];
    const rows = (d.candidates || []).map((c) =>
      `<tr data-sid="${esc(c.source_id)}"><td title="${esc(c.title)}"><span class="rx-rank"></span>${esc(c.title)}</td>` +
      crits.map((k) => `<td><span class="rx-cell pending" data-c="${k}">···</span></td>`).join("") + "</tr>").join("");
    el.innerHTML = `<div class="rx-a-kicker">&#9670; EVALUATION · CONSUMING ${esc(d.artifact_id)}</div>
      <h3>CANDIDATE CHECKS</h3>
      <div class="rx-host">${esc(hostLine(d.host))}</div>
      <table class="rx-m"><thead><tr><th>Candidate</th>${crits.map((k) => `<th>${esc(CRIT_LABEL[k] || k)}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody></table>
      <div class="rx-a-sum rx-eval-sum" style="margin-top:8px"></div>`;
    el.addEventListener("click", (e) => {
      const tr = e.target.closest("tr[data-sid]");
      if (tr) openViewer(tr.dataset.sid);
    });
    const src = S.artifacts[0];
    const start = src ? { x: src.x + src.w * 0.6, y: src.y + 30 } : { x: geometry().colB, y: 160 };
    el.style.transform = tf(start.x, start.y, 0.4);
    el.style.opacity = "0";
    R.root.appendChild(el);
    void el.offsetWidth;
    el.classList.remove("rx-forming");
    S.evalp = { el, criteria: crits, host: d.host, h: 0, comparison: null };
  }
  function setCell(d) {
    if (!S.evalp) return;
    const cell = S.evalp.el.querySelector(`tr[data-sid="${CSS.escape(d.source_id)}"] .rx-cell[data-c="${CSS.escape(d.criterion)}"]`);
    if (!cell) return;
    cell.className = `rx-cell v-${d.verdict}`;
    cell.textContent = d.verdict === "unknown" ? "UNKNOWN" : d.verdict.toUpperCase();
    cell.title = d.detail || "";
  }
  function morphToComparison(art) {
    if (!S.evalp) return;
    const el = S.evalp.el;
    S.evalp.comparison = art;
    el.classList.add("is-comparison");
    $(".rx-a-kicker", el).innerHTML = `&#9670; CONTEXT ARTIFACT · ${esc(art.type)} · DERIVED FROM ${esc((art.derived_from || []).join(", "))}`;
    $("h3", el).textContent = art.title;
    $(".rx-eval-sum", el).textContent = art.summary;
    // re-rank rows physically (FLIP) so the winner rises to the top
    const tbody = $("tbody", el);
    const rows = [...tbody.children];
    const first = new Map(rows.map((r) => [r, r.getBoundingClientRect().top]));
    (art.findings || []).forEach((f) => {
      const tr = tbody.querySelector(`tr[data-sid="${CSS.escape((f.source_ids || [])[0] || "")}"]`);
      if (tr) {
        $(".rx-rank", tr).textContent = `#${f.rank} · ${Number(f.fit_score).toFixed(2)}`;
        tbody.appendChild(tr);
      }
    });
    rows.forEach((r) => {
      const dy = first.get(r) - r.getBoundingClientRect().top;
      if (!dy) return;
      r.style.transition = "none";
      r.style.transform = `translate3d(0, ${dy}px, 0)`;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        r.style.transition = "";
        r.style.transform = "";
      }));
    });
    S.artifacts.push({ art, el, h: 0, isEval: true });
    renderDock();
  }

  // ------------------------------------------------------------ answer
  function showAnswer(text) {
    ensureRoot();
    R.answer.innerHTML = `<div class="rx-a-kicker">&#9670; ANSWER · FROM ${S.artifacts.length} CONTEXT ARTIFACT${S.artifacts.length === 1 ? "" : "S"}</div>
      <div>${esc(text)}</div>`;
    S.answer = text;
  }

  // ------------------------------------------------------------- dock
  function renderDock() {
    if (!R) return;
    R.dock.innerHTML = "";
    const open = h("button", "rx-btn", `&#9670; Research · ${esc(S.title || "")}`);
    open.addEventListener("click", () => setCollapsed(false));
    R.dock.appendChild(open);
    S.artifacts.forEach((a) => {
      const b = h("button", "rx-btn", esc(a.art.title));
      b.addEventListener("click", () => setCollapsed(false));
      R.dock.appendChild(b);
    });
  }

  // ------------------------------------------------------------ layout
  let layoutQueued = false;
  function scheduleLayout() {
    if (layoutQueued) return;
    layoutQueued = true;
    requestAnimationFrame(() => {
      layoutQueued = false;
      layout();
    });
  }

  function place(el, x, y, s, o, z) {
    el.style.transform = tf(x, y, s);
    el.style.opacity = String(o);
    if (z != null) el.style.zIndex = String(z);
  }

  function zoneOf(c, stage) {
    const st = c.src.state;
    const post = stage === "artifact" || stage === "evaluation" || stage === "response" || stage === "done";
    if (st === "selected") {
      if (post && S.artifacts.length) return "tucked";
      if (S.forming) return "converge";
      return "evidence";
    }
    if (post) return "receded";
    if (st === "inspecting" || st === "verifying") return "focus";
    if (st === "useful") return "useful";
    if (st === "rejected" || st === "failed") return "aside";
    return "incoming";
  }

  const LEVEL = { incoming: "lvl-compact", focus: "lvl-full", useful: "lvl-mid", evidence: "lvl-full", converge: "lvl-tab",
    tucked: "lvl-tab", aside: "lvl-bar", receded: "lvl-bar" };

  function layout() {
    if (!R || !S.opened) return;
    const g = geometry();
    const b = document.body.classList;

    // ---- stage plane, header, feed, task chip
    // the plane stays folded against the core until the session really starts
    const wsOpen = S.stage !== "task";
    R.stage.style.width = `${g.regionR - g.regionL + 28}px`;
    R.stage.style.height = `${g.bottom - g.top + 16}px`;
    R.stage.style.transform = `${tf(g.regionL - 14, g.top - 8, 1)} scaleX(${wsOpen ? 1 : 0.08})`;
    R.stage.style.opacity = String(wsOpen && !S.collapsed ? 1 : 0);
    R.header.style.width = `${g.regionR - g.regionL}px`;
    place(R.header, wsOpen ? g.regionL : g.regionL + 60, g.top, wsOpen ? 1 : 0.94, wsOpen && !S.collapsed ? 1 : 0, 60);
    const headerH = R.header.offsetHeight || 64;
    const top = g.top + headerH + 34;
    const feedW = Math.max(220, Math.min(340, g.regionL - 70));
    R.feed.style.width = `${feedW}px`;
    place(R.feed, wsOpen ? 26 : 6, g.top + 4, 1, wsOpen && !S.collapsed ? 1 : 0);
    // task chip: born at the core, docks into the header title
    const tw = R.task.offsetWidth || 120;
    if (S.taskDocked) place(R.task, g.regionL + 2, g.top - 26, 0.86, 0);
    else {
      const oc = orbCenter();
      place(R.task, oc.x - tw / 2, oc.y + 0.16 * g.vh, 1, 1, 61);
    }

    // ---- bucket cards
    const zones = { incoming: [], focus: [], useful: [], evidence: [], converge: [], tucked: [], aside: [], receded: [] };
    for (const c of S.cards.values()) {
      if (c.src.meta && c.src.meta.dismissed && c.src.state !== "rejected") c.src.state = "rejected";
      zones[zoneOf(c, S.stage)].push(c);
    }
    zones.incoming.sort((a, b) => a.order - b.order);
    zones.useful.sort((a, b) => (b.src.relevance || 0) - (a.src.relevance || 0));
    zones.evidence.sort((a, b) => (b.src.relevance || 0) - (a.src.relevance || 0));
    zones.tucked.sort((a, b) => (b.src.relevance || 0) - (a.src.relevance || 0));
    zones.converge.sort((a, b) => (b.src.relevance || 0) - (a.src.relevance || 0));
    zones.aside.sort((a, b) => (b.asideAt || 0) - (a.asideAt || 0));

    // capacity (virtualisation: only cards with a visible slot get DOM)
    const asideVisible = S.stage === "research" || S.stage === "selection" ? 4 : 0;
    const asideSlots = Math.min(zones.aside.length, asideVisible);
    const ASIDE_SLOT = 46;
    const asideTop = g.bottom - asideSlots * ASIDE_SLOT - (zones.aside.length > asideSlots ? 30 : 0);
    const incomingBottom = (zones.aside.length ? asideTop - 34 : g.bottom) - 8;

    const targets = []; // [card, x, y, scale, opacity, z, level, visible]
    // incoming column C — stacked by real height; overflow summarised
    let y = top, hiddenIncoming = 0;
    for (const c of zones.incoming) {
      const hh = (c.h || 92) + 8;
      if (y + hh > incomingBottom) { hiddenIncoming++; targets.push([c, g.colC, incomingBottom - 20, 0.9, 0, 10, LEVEL.incoming, false]); continue; }
      targets.push([c, g.colC, y, 1, 1, 20, LEVEL.incoming, true]);
      y += hh;
    }
    // focus column B
    let yb = top;
    for (const c of zones.focus) {
      targets.push([c, g.colB - 6, yb, 1.03, 1, 45, LEVEL.focus, true]);
      yb += (c.h || 220) * 1.03 + 12;
    }
    yb = Math.max(yb, top + (S.focusReserve || 0));
    for (const c of zones.useful) {
      const hh = (c.h || 120) + 10;
      if (yb + hh > g.bottom) { targets.push([c, g.colB, g.bottom - 30, 0.9, 0, 10, LEVEL.useful, false]); continue; }
      targets.push([c, g.colB, yb, 1, 0.92, 25, LEVEL.useful, true]);
      yb += hh;
    }
    // evidence cluster column A (closest to the core)
    let ya = top;
    const evLevel = zones.evidence.length > 2 ? "lvl-mid" : LEVEL.evidence;
    for (const c of zones.evidence) {
      targets.push([c, g.colA, ya, 1, 1, 35, evLevel, true]);
      ya += (c.h || 160) + 12;
    }
    // converge: evidence compresses together before the artifact forms
    zones.converge.forEach((c, i) => targets.push([c, g.colA + i * 8, top + 40 + i * 16, 0.97, 1, 35 + i, LEVEL.converge, true]));
    // set-aside tray (bottom of column C), newest on top
    zones.aside.forEach((c, i) => {
      if (i < asideSlots) targets.push([c, g.colC + 14, asideTop + i * ASIDE_SLOT, 0.9, 0.45 - i * 0.06, 5 - i, LEVEL.aside, true]);
      else targets.push([c, g.colC + 24, g.bottom - 10, 0.8, 0, 1, LEVEL.aside, false]);
    });

    // ---- artifacts + evaluation
    const art1 = S.artifacts.find((a) => !a.isEval);
    const hasEval = !!S.evalp;
    let artX = g.colA, artW = g.colC - g.colA - g.gap;
    if (art1) {
      if (hasEval) artW = Math.max(250, Math.min(330, g.cardW + 30));
      art1.el.classList.toggle("compact", hasEval);
      art1.el.style.width = `${artW}px`;
      art1.h = art1.el.offsetHeight;
      art1.x = artX; art1.y = top - 8; art1.w = artW;
      place(art1.el, artX, top - 8, 1, S.collapsed ? 0 : 1, 55);
      // the evidence stays traceable, tucked under the artifact
      zones.tucked.forEach((c, i) => targets.push([c, artX + 10 + i * 4, top - 8 + art1.h + 10 + i * 30, 1, S.collapsed ? 0 : 0.92, 50 - i, LEVEL.tucked, true]));
      art1.bottom = top - 8 + art1.h + 10 + zones.tucked.length * 30;
    }
    if (hasEval) {
      const ex = artX + artW + g.gap + 8;
      const ew = g.regionR - ex;
      S.evalp.el.style.width = `${ew}px`;
      S.evalp.h = S.evalp.el.offsetHeight;
      S.evalp.x = ex; S.evalp.y = top - 8;
      place(S.evalp.el, ex, top - 8, 1, S.collapsed ? 0 : 1, 56);
    }
    // receded research: pushed back and dimmed, still reachable
    zones.receded.sort((a, b) => a.order - b.order);
    zones.receded.forEach((c, i) => {
      const visible = !S.settled && i < 6;
      targets.push([c, g.regionR - g.cardW * 0.8 + 20, g.bottom - 40 - i * 26, 0.8, visible && !S.collapsed ? 0.16 : 0, 2, LEVEL.receded, visible]);
    });

    // ---- pass 1: create DOM for newly visible cards, set level, render
    const created = [];
    for (const t of targets) {
      const [c, , , , , , level, visible] = t;
      if (!c.el && visible) {
        makeCardEl(c);
        c.el.style.width = `${g.cardW}px`;
        c.el.style.transform = tf(g.regionR + 40, t[2] + 10, 0.92);
        c.el.style.opacity = "0";
        R.root.appendChild(c.el);
        created.push(c);
      }
      if (!c.el) continue;
      c.el.style.width = `${g.cardW}px`;
      if (c.level !== level) {
        if (c.level) c.el.classList.remove(c.level);
        c.el.classList.add(level);
        c.level = level;
        c.dirty = true;
      }
      if (c.dirty) { renderCard(c, c.changed); c.changed = null; c.dirty = false; }
      c.el.style.pointerEvents = visible && !S.collapsed ? "auto" : "none";
    }
    // ---- pass 2: measure (one reflow)
    let heightsChanged = false;
    for (const t of targets) {
      const c = t[0];
      if (!c.el) continue;
      const nh = c.el.offsetHeight;
      if (Math.abs(nh - (c.h || 0)) > 2) heightsChanged = true;
      c.h = nh;
    }
    // ---- pass 3: write positions
    for (const t of targets) {
      const [c, x, yy, s, o, z] = t;
      if (!c.el) continue;
      c.x = x; c.y = yy;
      if (created.includes(c)) {
        // entrance: from just beyond the right edge, soft blur, into its slot
        c.el.style.transitionDelay = "0ms";
        void c.el.offsetWidth;
        c.el.classList.remove("rx-entering");
      }
      place(c.el, x, yy, s, S.collapsed ? 0 : o, z);
    }
    if (zones.focus.length) S.focusReserve = Math.max(S.focusReserve || 0, (zones.focus[0].h || 0) * 1.03 + 14);

    // ---- labels + overflow chips
    const lab = (el, text, x, yy, show) => { if (text != null) el.innerHTML = text; place(el, x, yy, 1, show && !S.collapsed ? 1 : 0); };
    const research = S.stage === "research" || S.stage === "selection";
    lab(R.lIncoming, `INCOMING · <b>${zones.incoming.length}</b>`, g.colC, top - 20, research && zones.incoming.length > 0);
    lab(R.lFocus, zones.focus.length ? "INSPECTING" : `VERIFIED · <b>${zones.useful.length}</b>`, g.colB, top - 20, research && (zones.focus.length + zones.useful.length) > 0);
    lab(R.lEvidence, `EVIDENCE · <b>${zones.evidence.length + zones.converge.length}</b> KEPT`, g.colA, top - 20, research && (zones.evidence.length + zones.converge.length) > 0);
    lab(R.lAside, `SET ASIDE · <b>${zones.aside.length}</b>`, g.colC + 14, asideTop - 22, research && zones.aside.length > 0);
    lab(R.moreIncoming, `+${hiddenIncoming} additional sources`, g.colC, incomingBottom - 18, research && hiddenIncoming > 0);
    lab(R.moreAside, `+${zones.aside.length - asideSlots} more set aside`, g.colC + 14, g.bottom - 22, research && zones.aside.length > asideSlots);

    // ---- the answer lands under the artifacts it was derived from
    if (S.answer) {
      const below = Math.max(art1 ? art1.bottom || 0 : 0, hasEval ? S.evalp.y + S.evalp.h : 0, top) + 22;
      R.answer.style.width = `${g.regionR - g.regionL}px`;
      place(R.answer, g.regionL, below, 1, S.collapsed ? 0 : 1, 58);
    }

    // ---- links: core -> focus (inspection beam), artifact -> evaluation
    const oc = orbCenter();
    const f = zones.focus[0];
    if (f && f.el && !S.collapsed) {
      const tx = f.x - 4, ty = f.y + 24;
      R.beam.setAttribute("d", `M${oc.x + 40},${oc.y} C${(oc.x + tx) / 2},${oc.y} ${(oc.x + tx) / 2},${ty} ${tx},${ty}`);
      R.beam.style.opacity = "1";
    } else R.beam.style.opacity = "0";
    if (art1 && hasEval && !S.collapsed) {
      const x1 = art1.x + art1.w, y1 = art1.y + 40, x2 = S.evalp.x, y2 = S.evalp.y + 40;
      R.link.setAttribute("d", `M${x1},${y1} C${x1 + 20},${y1} ${x2 - 20},${y2} ${x2},${y2}`);
      R.link.style.opacity = "1";
    } else R.link.style.opacity = "0";

    if (heightsChanged) scheduleLayout(); // settle once after content changes height
  }

  // ------------------------------------------------------------ header
  function renderHeader() {
    if (!R) return;
    R.hTitle.textContent = `◆ RESEARCH · ${S.title}`;
    R.hPct.textContent = `${Math.round(S.percent)}%`;
    R.hBar.style.transform = `scaleX(${Math.max(0, Math.min(1, S.percent / 100))})`;
    const c = S.counts || {};
    const n = (k) => c[k] || 0;
    const discovered = Object.values(c).reduce((a, v) => a + v, 0);
    const inspected = n("useful") + n("selected") + n("failed") + [...S.cards.values()].filter((x) => x.src.state === "rejected" && x.src.inspection_status === "done").length;
    R.hCounts.innerHTML = [
      ["DISCOVERED", discovered], ["INSPECTED", inspected], ["KEPT", n("selected")], ["SET ASIDE", n("rejected")],
    ].concat(n("failed") ? [["FAILED", n("failed")]] : []).map(([k, v]) => `<span>${k} <b>${v}</b></span>`).join("");
    const pause = $('[data-act="pause"]', R.header);
    pause.textContent = S.paused ? "Resume" : "Pause";
    pause.disabled = S.finished;
    $('[data-act="stop"]', R.header).disabled = S.finished;
    $('[data-act="close"]', R.header).style.display = S.finished ? "" : "none";
  }

  function setStageLabel(label) {
    if (R) R.hStage.textContent = label;
  }

  // ------------------------------------------------------------ lifecycle
  function reset() {
    if (R) {
      R.root.remove();
      R.pulse.remove();
      R = null;
    }
    feedLines.length = 0;
    Object.assign(S, {
      sid: null, title: "", stage: "idle", opened: false, settled: false, collapsed: false, paused: false, finished: false,
      percent: 0, counts: {}, cards: new Map(), arrival: 0, artifacts: [], forming: null, evalp: null, answer: null,
      focusReserve: 0, taskDocked: false,
    });
    S.viewer = { open: false, id: null, tab: "facts", detail: null, mode: "source" };
    document.body.classList.remove("rx-active", "rx-settled", "rx-collapsed", "rx-paused");
  }

  function beginTask(ev) {
    reset();
    ensureRoot();
    S.sid = ev.session_id;
    S.title = ev.data.title || "RESEARCH";
    R.task.textContent = `◆ ${S.title}`;
    // the core acknowledges: a pulse from its centre, then attention shifts
    const oc0 = orbCenter();
    R.pulse.style.left = `${oc0.x}px`;
    R.pulse.style.top = `${oc0.y}px`;
    R.pulse.classList.add("go");
    S.opened = true; // header etc. still transparent until session.started
    R.stage.style.transform = tf(0, 0, 1);
    document.body.classList.add("rx-active");
    const g = geometry();
    // the workspace plane grows out of the space beside the core
    R.stage.style.transition = "none";
    R.stage.style.opacity = "0";
    R.header.style.opacity = "0";
    R.stage.style.transform = `${tf(g.regionL - 14, g.top - 8, 1)} scaleX(0.08)`;
    R.header.style.transform = tf(g.regionL + 60, g.top, 0.94);
    void R.stage.offsetWidth;
    R.stage.style.transition = "";
    const tw = R.task.offsetWidth || 120;
    const oc = orbCenter();
    R.task.style.transform = tf(oc0.x - tw / 2, oc0.y, 0.6);
    requestAnimationFrame(() => place(R.task, oc.x - tw / 2, oc.y + 0.16 * g.vh, 1, 1, 61));
    S.stage = "task";
  }

  function openWorkspace(ev) {
    ensureRoot();
    const provs = (ev.data.providers || []).map((p) => p.label).join(" · ");
    setStageLabel("RESEARCH");
    S.stage = "research";
    S.taskDocked = true;
    renderHeader();
    R.header.title = provs ? `Providers: ${provs}` : "";
    scheduleLayout();
  }

  function setCollapsed(v) {
    S.collapsed = v;
    document.body.classList.toggle("rx-collapsed", v);
    const btn = R && $('[data-act="collapse"]', R.header);
    if (btn) btn.textContent = v ? "Expand" : "Collapse";
    renderDock();
    scheduleLayout();
  }

  function settle() {
    S.finished = true;
    S.settled = true;
    document.body.classList.add("rx-settled");
    renderHeader();
    scheduleLayout();
  }

  // ------------------------------------------------------------- apply
  function apply(ev) {
    const d = ev.data || {};
    if (ev.type === "task.started") { beginTask(ev); return; }
    if (!S.sid) {
      // joined mid-session (page reload): adopt it
      S.sid = ev.session_id;
      ensureRoot();
      S.opened = true;
      S.taskDocked = true;
      S.stage = "research";
      document.body.classList.add("rx-active");
    }
    if (ev.session_id && ev.session_id !== S.sid) return; // one live workspace at a time
    const isSrc = d.source && d.source.source_id;
    switch (ev.type) {
      case "research.session.started":
        S.title = d.title || S.title;
        openWorkspace(ev);
        break;
      case "research.result.discovered":
      case "research.source.queued":
      case "research.source.inspecting":
      case "research.source.verifying":
      case "research.source.useful":
      case "research.source.selected":
        if (isSrc) upsert(d.source);
        break;
      case "research.source.metadata_updated":
        if (isSrc) upsert(d.source, d.changed);
        break;
      case "research.source.rejected":
      case "research.source.failed":
        if (isSrc) { const c = upsert(d.source); c.asideAt = ev.seq; }
        break;
      case "research.progress.updated":
        S.percent = d.percent || 0;
        S.counts = d.counts || {};
        renderHeader();
        return;
      case "research.activity":
        pushFeed(d.text || "", d.kind);
        return;
      case "research.query.failed":
        return; // the activity line carries the honest failure text
      case "stage.changed":
        S.stage = d.stage;
        setStageLabel(d.label || String(d.stage).toUpperCase());
        break;
      case "research.artifact.creating":
        if (d.artifact_type !== "CANDIDATE_COMPARISON") S.forming = { ids: d.source_ids || [] };
        setStageLabel(`FORMING · ${d.title}`);
        break;
      case "research.artifact.created": {
        const art = d.artifact;
        if (art.type === "CANDIDATE_COMPARISON" && S.evalp) morphToComparison(art);
        else createArtifact(art);
        S.forming = null;
        setStageLabel(art.title);
        break;
      }
      case "benchmark.started":
        createEval(d);
        setStageLabel("EVALUATION");
        break;
      case "benchmark.result":
        setCell(d);
        return;
      case "response.ready":
        showAnswer(d.text || "");
        break;
      case "research.completed":
        setStageLabel("COMPLETE");
        settle();
        break;
      case "research.session.paused":
        S.paused = true;
        document.body.classList.add("rx-paused");
        setStageLabel("PAUSED");
        renderHeader();
        return;
      case "research.session.resumed":
        S.paused = false;
        document.body.classList.remove("rx-paused");
        setStageLabel(S.stage.toUpperCase());
        renderHeader();
        return;
      case "research.session.stopped":
        setStageLabel("STOPPED");
        settle();
        break;
      case "task.completed":
        if (d.status === "failed") { setStageLabel("FAILED"); settle(); }
        break;
      default:
        break;
    }
    renderHeader();
    scheduleLayout();
    if (S.viewer.open && isSrc && S.viewer.id === d.source.source_id && S.viewer.mode === "source") refreshViewer();
  }

  // ------------------------------------------------------ paced queue
  const queue = [];
  let busyUntil = 0, pumping = false, timer = null;
  function speed() {
    const n = queue.length;
    return n > 80 ? 0 : n > 40 ? 0.25 : n > 18 ? 0.6 : 1;
  }
  function enqueue(ev) {
    if (!ev || ev.seq <= S.lastSeq) return;
    S.lastSeq = ev.seq;
    queue.push(ev);
    pump();
  }
  function pump() {
    if (pumping) return;
    pumping = true;
    try {
      let n = 0;
      while (queue.length && performance.now() >= busyUntil && n < 80) {
        const ev = queue.shift();
        try { apply(ev); } catch (e) { console.error("[research] apply failed", ev.type, e); }
        busyUntil = performance.now() + (DWELL[ev.type] || 0) * speed();
        n++;
      }
    } finally {
      pumping = false;
    }
    if (queue.length && !timer) {
      timer = setTimeout(() => { timer = null; pump(); }, Math.max(8, busyUntil - performance.now()));
    }
  }

  // ------------------------------------------------------------- viewer
  function openViewer(id) {
    ensureRoot();
    S.viewer.open = true;
    S.viewer.id = id;
    S.viewer.mode = "source";
    R.viewer.classList.add("open");
    for (const c of S.cards.values()) if (c.el) c.el.classList.toggle("focus-ring", c.id === id);
    refreshViewer();
  }
  function closeViewer() {
    S.viewer.open = false;
    if (R) R.viewer.classList.remove("open");
    for (const c of S.cards.values()) if (c.el) c.el.classList.remove("focus-ring");
  }
  function refreshViewer() {
    const c = S.cards.get(S.viewer.id);
    if (!c) return;
    renderViewer(c.src, S.viewer.detail && S.viewer.detail.source_id === c.id ? S.viewer.detail : null);
    const sock = socket();
    if (sock) sock.emit("research_source_detail", { source_id: c.id }, (detail) => {
      if (!detail || detail.error || S.viewer.id !== c.id) return;
      S.viewer.detail = detail;
      renderViewer(detail, detail);
    });
  }
  function renderViewer(src, detail) {
    const v = R.viewer;
    $(".rx-v-title", v).textContent = src.title;
    $(".rx-v-url", v).textContent = src.url;
    $(".rx-v-sub", v).textContent = `${src.provider} · ${src.source_type} · ${BADGE[src.state] || src.state} · retrieved ${hhmmss(src.retrieved_at)}`;
    const pinned = src.meta && src.meta.pinned;
    $(".rx-v-actions", v).innerHTML = `
      <button class="rx-btn" data-act="open">Open source</button>
      <button class="rx-btn" data-act="copy">Copy link</button>
      <button class="rx-btn" data-act="${pinned ? "unpin" : "pin"}">${pinned ? "Unpin" : "Pin"}</button>
      <button class="rx-btn warn" data-act="dismiss" ${src.state === "rejected" ? "disabled" : ""}>Dismiss</button>
      <button class="rx-btn" data-act="closev">Close</button>`;
    const tabs = [["facts", "Facts"], ["meta", "Metadata"], ["preview", "Preview"], ["why", "Why"]];
    $(".rx-v-tabs", v).innerHTML = tabs.map(([k, t]) => `<button class="rx-v-tab ${S.viewer.tab === k ? "on" : ""}" data-tab="${k}">${t}</button>`).join("");
    const body = $(".rx-v-body", v);
    const tab = S.viewer.tab;
    if (tab === "facts") {
      const facts = src.facts || [];
      body.innerHTML = facts.length
        ? facts.map((f) => `<div class="rx-fact"><span class="l">${esc(f.label)}</span><span class="v">${esc(f.value)}<div class="rx-v-origin">from ${esc(f.origin)}</div></span></div>`).join("")
        : `<pre>No facts extracted yet — inspection has ${src.inspection_status === "pending" ? "not started" : "not produced any"}.</pre>`;
    } else if (tab === "meta") {
      const meta = Object.assign({}, src.meta || {});
      const raw = detail ? detail.raw_metadata : null;
      body.innerHTML = `<pre>${esc(JSON.stringify(meta, null, 1))}</pre>` +
        (raw ? `<div class="rx-v-sub" style="margin:10px 0 4px">RAW PROVIDER METADATA</div><pre>${esc(JSON.stringify(raw, null, 1).slice(0, 12000))}</pre>` : "");
    } else if (tab === "preview") {
      body.innerHTML = detail
        ? (detail.preview ? `<pre>${esc(detail.preview.slice(0, 12000))}</pre>` : "<pre>No content fetched for this source.</pre>")
        : "<pre>Loading…</pre>";
    } else {
      body.innerHTML = `<pre>${esc([
        `State: ${src.state}`,
        `Inspection: ${src.inspection_status}`,
        `Verification: ${src.verification_status}`,
        `Score: ${src.relevance == null ? "—" : src.relevance}`,
        src.error ? `Error: ${src.error}` : "",
        "",
        ...(src.reasons || []).map((r) => "• " + r),
      ].filter((x) => x !== null).join("\n"))}</pre>`;
    }
  }
  function openSourceList(which) {
    ensureRoot();
    S.viewer.open = true;
    S.viewer.mode = "list";
    R.viewer.classList.add("open");
    const v = R.viewer;
    const groups = [["selected", "KEPT"], ["useful", "VERIFIED"], ["inspecting", "INSPECTING"], ["verifying", "VERIFYING"],
      ["queued", "QUEUED"], ["discovered", "DISCOVERED"], ["failed", "FAILED"], ["rejected", "SET ASIDE"]];
    const all = [...S.cards.values()];
    $(".rx-v-title", v).textContent = `All sources · ${all.length}`;
    $(".rx-v-url", v).textContent = S.title;
    $(".rx-v-sub", v).textContent = which === "aside" ? "Set-aside sources are kept for provenance" : "Every discovered source, grouped by state";
    $(".rx-v-actions", v).innerHTML = `<button class="rx-btn" data-act="closev">Close</button>`;
    $(".rx-v-tabs", v).innerHTML = "";
    $(".rx-v-body", v).innerHTML = groups.map(([st, label]) => {
      const items = all.filter((c) => c.src.state === st);
      if (!items.length) return "";
      return `<div class="rx-v-sub" style="margin:8px 0 2px">${label} · ${items.length}</div>` + items.map((c) =>
        `<div class="rx-v-list-item" data-sid="${esc(c.id)}"><span>${esc(c.src.title)}</span><span class="s">${esc(c.src.provider)}</span></div>`).join("");
    }).join("");
  }
  function onViewerClick(e) {
    const item = e.target.closest(".rx-v-list-item");
    if (item) { openViewer(item.dataset.sid); return; }
    const tab = e.target.closest("[data-tab]");
    if (tab) { S.viewer.tab = tab.dataset.tab; refreshViewer(); return; }
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    const c = S.cards.get(S.viewer.id);
    if (act === "closev") return closeViewer();
    if (act === "follow") return sendFollowup();
    if (!c) return;
    if (act === "open") {
      if (/^https?:/i.test(c.src.url)) window.open(c.src.url, "_blank", "noopener");
      else { S.viewer.tab = "preview"; refreshViewer(); }
    } else if (act === "copy") {
      (navigator.clipboard ? navigator.clipboard.writeText(c.src.url) : Promise.reject()).then(
        () => pushFeed(`Link copied — ${c.src.title}`, "control"), () => window.prompt("Copy link", c.src.url));
    } else if (act === "pin" || act === "unpin" || act === "dismiss") {
      const sock = socket();
      if (sock) sock.emit("research_source_action", { session_id: S.sid, source_id: c.id, action: act });
    }
  }
  function sendFollowup() {
    const input = $(".rx-v-follow input", R.viewer);
    const text = input.value.trim();
    const ids = S.viewer.mode === "source" && S.viewer.id ? [S.viewer.id]
      : [...S.cards.values()].filter((c) => c.src.state === "selected").map((c) => c.id);
    if (!ids.length) return;
    const sock = socket();
    if (sock) sock.emit("research_followup", { session_id: S.sid, source_ids: ids, text });
    input.value = "";
    pushFeed(`Follow-up sent with ${ids.length} source${ids.length === 1 ? "" : "s"} as context`, "control");
  }

  function onHeaderClick(e) {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const sock = socket();
    const act = btn.dataset.act;
    if (act === "pause") sock && sock.emit("research_control", { session_id: S.sid, action: S.paused ? "resume" : "pause" });
    else if (act === "stop") sock && sock.emit("research_control", { session_id: S.sid, action: "stop" });
    else if (act === "collapse") setCollapsed(!S.collapsed);
    else if (act === "sources") openSourceList("all");
    else if (act === "close") reset();
  }

  // ------------------------------------------------------------ socket
  let sockRef = null;
  function socket() {
    return sockRef || window.__jarvisSocket || null;
  }
  function attach(sock) {
    if (!sock || sock.__rxAttached) return;
    sock.__rxAttached = true;
    sockRef = sock;
    sock.on("research_event", enqueue);
    let wasConnected = sock.connected;
    sock.on("connect", () => {
      // after a drop, replay everything we missed — never re-simulate
      if (wasConnected || S.lastSeq > 0) {
        sock.emit("research_replay", { since: S.lastSeq }, (events) => {
          (events || []).forEach(enqueue);
        });
      }
      wasConnected = true;
    });
  }
  function init() {
    if (window.__jarvisSocket) attach(window.__jarvisSocket);
    else if (window.io) attach(window.io({ transports: ["websocket", "polling"] }));
    window.addEventListener("resize", scheduleLayout);
  }

  window.MentisResearch = {
    start(text) { const s = socket(); if (s && text) s.emit("research_start", { text }); },
    attach,
    state: S,
    _enqueue: enqueue, // test hook: feeds recorded REAL events for replay
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
