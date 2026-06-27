"use strict";

const VERDICT_KO = {
  QUALIFIED: "진출 확정",
  CLINCHED: "진출 확정",
  CONTENDING: "경합 중",
  ELIMINATED: "탈락",
};

let STATE = null;

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html !== undefined) n.innerHTML = html;
  return n;
};

async function loadState(refresh = false) {
  $("#metaLine").textContent = refresh ? "최신 데이터 갱신 중…" : "데이터 불러오는 중…";
  $("#refreshBtn").disabled = true;
  document.body.classList.add("spin");
  try {
    const res = await fetch("/api/state" + (refresh ? "?refresh=1" : ""));
    STATE = await res.json();
    render();
  } catch (e) {
    $("#metaLine").textContent = "데이터 로드 실패: " + e;
  } finally {
    $("#refreshBtn").disabled = false;
    document.body.classList.remove("spin");
  }
}

function render() {
  renderMeta();
  renderVerdict();
  renderBingo(STATE.bingo, STATE.probability);
  renderKoreaGroup();
  renderThird();
  renderThreat();
  renderWhatif();
  renderPredictions();
  renderAllGroups();
}

const TIER_CLASS = { "강세": "t-strong", "우세": "t-fav", "약우세": "t-slight", "백중": "t-even" };

function renderPredictions() {
  const box = $("#predList");
  if (!box) return;
  const preds = STATE.predictions || [];
  box.innerHTML = "";
  if (!preds.length) {
    box.innerHTML = `<p class="hint">남은 경기가 없습니다.</p>`;
    return;
  }
  preds.forEach((p) => {
    const ph = Math.round(p.p_home * 100);
    const pd = Math.round(p.p_draw * 100);
    const pa = Math.round(p.p_away * 100);
    const tierCls = TIER_CLASS[p.tier] || "t-even";
    const row = el("div", "pred");
    row.innerHTML =
      `<div class="pred-top">` +
      `<span class="gtag">${p.group}조</span>` +
      `<span class="pname home">${p.home}</span>` +
      `<span class="pvs">vs</span>` +
      `<span class="pname away">${p.away}</span>` +
      (p.date ? `<span class="wdate">${p.date.slice(5)}</span>` : "") +
      `<span class="ptier ${tierCls}">${p.summary}</span>` +
      `</div>` +
      `<div class="pbar">` +
      `<i class="bh" style="width:${ph}%" title="홈 승 ${ph}%"></i>` +
      `<i class="bd" style="width:${pd}%" title="무 ${pd}%"></i>` +
      `<i class="ba" style="width:${pa}%" title="원정 승 ${pa}%"></i>` +
      `</div>` +
      `<div class="pnums"><span>${p.home} ${ph}%</span><span>무 ${pd}%</span><span>${p.away} ${pa}%</span></div>`;
    box.appendChild(row);
  });
}

const MARK = { favorable: "○", unfavorable: "✕", pending: "?" };

function renderBingo(b, mc) {
  const grid = $("#bingoGrid");
  const headline = $("#bingoHeadline");
  const progress = $("#bingoProgress");
  if (!b || !b.available) {
    grid.innerHTML = `<p class="hint">빙고판 데이터를 사용할 수 없습니다.</p>`;
    headline.textContent = "";
    progress.textContent = "";
    return;
  }
  headline.className = "bingo-headline" +
    (b.status === "CLINCHED" || b.status === "QUALIFIED" ? " clinch" : b.status === "ELIMINATED" ? " elim" : "");
  headline.textContent = b.headline || "";

  if (typeof b.favorable_needed === "number") {
    progress.innerHTML =
      `필요 <b>${b.favorable_needed}</b>팀 · 확보 <b style="color:var(--green)">${b.secured}</b> · ` +
      `미정 <b style="color:#7ab8ff">${b.pending}</b> · 불리확정 <b style="color:var(--red)">${b.unfavorable_locked}</b>`;
  } else {
    progress.textContent = "";
  }

  const groupAbove = (mc && mc.group_above_prob) || {};
  grid.innerHTML = "";
  (b.cells || []).forEach((c) => {
    const cell = el("div", "bcell " + c.status);
    let body = `<span class="mark">${MARK[c.status]}</span>` +
      `<div class="gname">${c.group}조</div>`;
    if (c.third_now) {
      body += `<div class="third">현재 3위: ${c.third_now} (승점 ${c.third_now_pts}, GD ${c.third_now_gd >= 0 ? "+" : ""}${c.third_now_gd})</div>`;
    }
    if (c.status === "pending" && c.conditions && c.conditions.length) {
      body += "<ul>" + c.conditions.map((cc) => `<li>${cc.text}</li>`).join("") + "</ul>";
      const p = groupAbove[c.group];
      if (typeof p === "number") {
        body += `<span class="prob">유리 확률 ${Math.round((1 - p) * 100)}%</span>`;
      }
    } else if (c.locked) {
      body += `<div class="locked-msg">${c.status === "favorable" ? "한국보다 아래 — 확정 ○" : "한국보다 위 — 확정 ✕"}</div>`;
    }
    cell.innerHTML = body;
    grid.appendChild(cell);
  });
  if (!b.cells || !b.cells.length) {
    grid.innerHTML = `<p class="hint">${b.headline || "추가 변수가 없습니다."}</p>`;
  }
}

function renderMeta() {
  const m = STATE.meta;
  const srcName = { fifa: "FIFA 공식 API", openfootball: "openfootball", cache: "로컬 캐시" }[m.source] || m.source;
  $("#metaLine").innerHTML =
    `출처 <b>${srcName}</b> · ${m.finished}/${m.total_matches} 경기 종료 · 갱신 ${m.fetched_at}` +
    (m.errors && m.errors.length ? ` · <span style="color:#f59e0b">일부 소스 실패</span>` : "");
}

function renderVerdict() {
  const a = STATE.analysis;
  const v = a.verdict;
  const badge = $("#verdictBadge");
  badge.className = "verdict-badge " + v;
  badge.textContent = VERDICT_KO[v] || v;
  $("#verdictText").textContent = a.verdict_text || "";

  const mc = STATE.probability;
  if (mc && typeof mc.advance_prob === "number") {
    const pct = Math.round(mc.advance_prob * 1000) / 10;
    $("#gaugeNum").textContent = pct + "%";
    $("#gauge").style.setProperty("--p", pct + "%");
    $("#gaugeSub").textContent = mc.trials
      ? `(몬테카를로 ${mc.trials.toLocaleString()}회 추정)`
      : `(조별 독립 정확 계산)`;
  }
  // 확정/탈락이면 게이지 색 고정
  const g = $("#gauge");
  if (v === "QUALIFIED" || v === "CLINCHED") g.style.setProperty("--p", "100%");
  if (v === "ELIMINATED") { $("#gaugeNum").textContent = "0%"; g.style.setProperty("--p", "0%"); }
}

function teamRow(t, opts = {}) {
  const tr = el("tr", `pos${t.rank}` + (opts.korea ? " korea" : "") + (t.rank <= 2 ? " qualify" : ""));
  tr.innerHTML =
    `<td class="rank">${t.rank}</td>` +
    `<td class="team">${t.name}</td>` +
    `<td>${t.played}</td><td>${t.win}</td><td>${t.draw}</td><td>${t.loss}</td>` +
    `<td>${t.gf}:${t.ga}</td><td>${t.gd >= 0 ? "+" : ""}${t.gd}</td>` +
    `<td><b>${t.points}</b></td>`;
  return tr;
}

function standingsTable(table, koreaName) {
  const tbl = el("table");
  tbl.innerHTML =
    `<thead><tr><th class="rank">#</th><th class="team">팀</th><th>경기</th>` +
    `<th>승</th><th>무</th><th>패</th><th>득실</th><th>+/-</th><th>승점</th></tr></thead>`;
  const tb = el("tbody");
  table.forEach((t) => tb.appendChild(teamRow(t, { korea: t.name === koreaName })));
  tbl.appendChild(tb);
  return tbl;
}

function renderKoreaGroup() {
  const a = STATE.analysis;
  const g = a.korea_group;
  $("#koreaGroupTitle").innerHTML =
    `한국 조 순위 — <b>${g}조</b> ` +
    (STATE.groups[g].complete ? `<span class="tag done">조 완료</span>` : `<span class="tag open">진행중</span>`);
  const box = $("#koreaTable");
  box.innerHTML = "";
  box.appendChild(standingsTable(STATE.groups[g].table, a.korea_name));
  const ranks = a.possible_group_ranks || [];
  $("#koreaHint").innerHTML =
    `한국 조내 순위: <b>${a.korea_rank_in_group}위</b> (승점 ${a.korea_stats.points}, 골득실 ${a.korea_stats.gd >= 0 ? "+" : ""}${a.korea_stats.gd})` +
    (ranks.length > 1 ? ` · 잔여경기 후 가능 순위: ${ranks.join(", ")}위` : "") +
    (a.korea_provisional_third_rank ? ` · 현재 3위 경쟁 <b>${a.korea_provisional_third_rank}위</b>/12 (컷 8위)` : "");
}

function renderThird() {
  const thirds = STATE.analysis.third_table || [];
  const korea = STATE.analysis.korea_name;
  const tbl = el("table");
  tbl.innerHTML =
    `<thead><tr><th class="rank">#</th><th class="team">조 · 팀</th>` +
    `<th>승점</th><th>+/-</th><th>득점</th><th>진출</th></tr></thead>`;
  const tb = el("tbody");
  thirds.forEach((t) => {
    const tr = el("tr", (t.name === korea ? "korea " : "") + (t.third_rank === 8 ? "cutline" : ""));
    tr.innerHTML =
      `<td class="rank">${t.third_rank}</td>` +
      `<td class="team">${t.group}조 · ${t.name}</td>` +
      `<td><b>${t.points}</b></td><td>${t.gd >= 0 ? "+" : ""}${t.gd}</td><td>${t.gf}</td>` +
      `<td class="${t.cut ? "cut-yes" : "cut-no"}">${t.cut ? "✅" : "❌"}</td>`;
    tb.appendChild(tr);
  });
  tbl.appendChild(tb);
  const box = $("#thirdTable");
  box.innerHTML = "";
  box.appendChild(tbl);
}

function renderThreat() {
  const det = STATE.analysis.wildcard_detail || [];
  const probs = (STATE.probability && STATE.probability.group_above_prob) || {};
  const box = $("#threatTable");
  box.innerHTML = "";
  const incomplete = det.filter((d) => !d.complete);
  if (!incomplete.length) {
    box.innerHTML = `<p class="hint">모든 다른 조가 종료되어 추가 변수는 없습니다.</p>`;
    return;
  }
  incomplete
    .sort((x, y) => (probs[y.group] || 0) - (probs[x.group] || 0))
    .forEach((d) => {
      const p = (probs[d.group] || 0) * 100;
      const row = el("div", "threat-row");
      row.innerHTML =
        `<span class="g">${d.group}조</span>` +
        `<div class="bar"><i style="width:${p.toFixed(0)}%"></i></div>` +
        `<span class="pct">${p.toFixed(0)}%</span>` +
        `<span class="rng">3위 승점 ${d.third_min_pts}~${d.third_max_pts}</span>`;
      box.appendChild(row);
    });
  box.appendChild(
    el("p", "hint",
      "막대 = 이 조의 3위가 한국보다 위에 설 확률(정확 계산). 높을수록 한국에 위협적입니다.")
  );
}

function renderWhatif() {
  const list = $("#whatifList");
  list.innerHTML = "";
  (STATE.remaining_matches || []).forEach((m) => {
    const wi = el("div", "wi");
    const md = m.date ? `<span class="wdate">${m.date.slice(5)}</span>` : "";
    wi.innerHTML =
      `<span class="gtag">${m.group}조</span>` +
      `<span class="match">${m.home} <b>vs</b> ${m.away}</span>` +
      md;
    const sel = el("select");
    sel.dataset.id = m.id;
    sel.innerHTML =
      `<option value="">미정</option>` +
      `<option value="home">${m.home} 승</option>` +
      `<option value="draw">무승부</option>` +
      `<option value="away">${m.away} 승</option>`;
    wi.appendChild(sel);
    list.appendChild(wi);
  });
  if (!STATE.remaining_matches.length) {
    list.innerHTML = `<p class="hint">잔여 경기가 없습니다. 모든 결과가 확정되었습니다.</p>`;
  }
}

async function runWhatif() {
  const outcomes = {};
  document.querySelectorAll("#whatifList select").forEach((s) => {
    if (s.value) outcomes[s.dataset.id] = s.value;
  });
  $("#whatifResult").textContent = "계산 중…";
  const res = await fetch("/api/whatif", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outcomes }),
  });
  const data = await res.json();
  const a = data.analysis;
  const advance = a.verdict === "QUALIFIED" || a.verdict === "CLINCHED";
  const out = $("#whatifResult");
  out.style.color = advance ? "var(--green)" : a.verdict === "ELIMINATED" ? "var(--red)" : "var(--amber)";
  out.innerHTML =
    `${advance ? "✅ 진출" : a.verdict === "ELIMINATED" ? "❌ 탈락" : "⚖ 경합"} — ` +
    `${a.verdict_text}` +
    (a.korea_provisional_third_rank ? ` (3위 경쟁 ${a.korea_provisional_third_rank}위)` : "");
  // 빙고판도 가정 결과 반영해 갱신 (확률 막대는 라이브 값 유지)
  if (data.bingo) renderBingo(data.bingo, STATE.probability);
}

function renderAllGroups() {
  const wrap = $("#allGroups");
  wrap.innerHTML = "";
  Object.keys(STATE.groups).sort().forEach((g) => {
    const gc = el("div", "gcard");
    const head = el("h3", null,
      `<span>${g}조</span>` +
      (STATE.groups[g].complete ? `<span class="tag done">완료</span>` : `<span class="tag open">진행중</span>`));
    gc.appendChild(head);
    gc.appendChild(standingsTable(STATE.groups[g].table, STATE.analysis.korea_name));
    wrap.appendChild(gc);
  });
}

// events
$("#refreshBtn").addEventListener("click", () => loadState(true));
$("#whatifBtn").addEventListener("click", runWhatif);
$("#whatifReset").addEventListener("click", () => {
  document.querySelectorAll("#whatifList select").forEach((s) => (s.value = ""));
  $("#whatifResult").textContent = "";
});

loadState(false);
