let allMinisters = [];
let currentMinisters = []; // may differ from allMinisters when in time-machine mode
let snapshotMeta = [];     // [{index, timestamp, count}, ...]
let isTimeMachine = false;
let countdown = 7 * 24 * 60 * 60; // seconds (1 week)

// ── Init ──────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadData();
  loadSnapshotMeta();
  setInterval(tickCountdown, 1000);
  setInterval(loadData, 7 * 24 * 60 * 60 * 1000); // auto-refresh every 1 week
});

// ── Data loading ──────────────────────────────────────────
async function loadData() {
  if (isTimeMachine) return; // don't overwrite time-machine view
  setStatus("loading");
  try {
    const res = await fetch("/api/ministers");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    allMinisters = data.ministers || [];
    currentMinisters = allMinisters;
    renderCards(currentMinisters);
    renderHistory(data.history || []);
    updateMeta(data);
    setStatus("live");
    resetCountdown();
  } catch (err) {
    console.error("loadData error:", err);
    setStatus("error");
    showToast("데이터 로드 실패: " + err.message);
  }
}

async function loadSnapshotMeta() {
  try {
    const res = await fetch("/api/snapshots");
    if (!res.ok) return;
    const data = await res.json();
    snapshotMeta = data.snapshots || [];
    buildSlider();
  } catch (err) {
    console.warn("snapshot meta load failed:", err);
  }
}

async function manualRefresh() {
  const btn = document.getElementById("btn-refresh");
  btn.disabled = true;
  btn.classList.add("spinning");
  setStatus("loading");
  showToast("서버에서 최신 데이터를 가져오는 중...");

  try {
    const res = await fetch("/api/refresh", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const info = await res.json();
    showToast(`갱신 완료 — 국무위원 ${info.count}명 (${info.elapsed}s)`);
    isTimeMachine = false;
    await loadData();
    await loadSnapshotMeta();
  } catch (err) {
    setStatus("error");
    showToast("갱신 실패: " + err.message);
  } finally {
    btn.disabled = false;
    btn.classList.remove("spinning");
  }
}

// ── Render: cards ─────────────────────────────────────────
function renderCards(ministers, label) {
  const grid = document.getElementById("cards-grid");
  const title = document.getElementById("panel-title");
  title.textContent = label || "현 내각 구성원";

  if (!ministers.length) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1">
      데이터를 불러올 수 없습니다.<br>새로고침 버튼을 눌러 다시 시도하세요.
    </div>`;
    document.getElementById("stat-total").textContent = 0;
    return;
  }

  grid.innerHTML = ministers.map((m, i) => `
    <div class="minister-card" onclick="openProfile(${i})" data-idx="${i}">
      ${m.photo
        ? `<img class="minister-avatar" src="${m.photo}" alt="${esc(m.name)}"
              onerror="this.replaceWith(makeAvatarEl('${esc(m.name[0])}'))">`
        : `<div class="minister-avatar-placeholder">${esc(m.name[0] || "?")}</div>`
      }
      <div class="minister-name">${esc(m.name)}</div>
      <div class="minister-title">${esc(m.title || "직책 미확인")}</div>
      ${m.appointed ? `<div class="minister-appointed">${esc(m.appointed)}</div>` : ""}
      <div class="minister-source">${esc(m.source || "")}</div>
    </div>
  `).join("");

  document.getElementById("stat-total").textContent = ministers.length;
  const sources = [...new Set(ministers.map(m => m.source))];
  document.getElementById("stat-source").textContent = sources.join(", ");
}

function makeAvatarEl(letter) {
  const div = document.createElement("div");
  div.className = "minister-avatar-placeholder";
  div.textContent = letter || "?";
  return div;
}

// ── Render: history ───────────────────────────────────────
function renderHistory(history) {
  const list = document.getElementById("history-list");
  document.getElementById("stat-changes").textContent = history.length;

  if (!history.length) {
    list.innerHTML = `<div class="empty-state">변경 이력이 없습니다.</div>`;
    return;
  }

  list.innerHTML = history.map(h => `
    <div class="history-item">
      <span class="badge ${esc(h.type)}">${esc(h.type)}</span>
      <div class="history-title">${esc(h.title)}</div>
      <div class="history-name">${esc(h.name)}</div>
      ${h.prev_name ? `<div class="history-prev">← ${esc(h.prev_name)}</div>` : ""}
      <div class="history-time">${esc(h.timestamp)}</div>
    </div>
  `).join("");
}

// ── Search / filter ───────────────────────────────────────
function filterCards() {
  const q = document.getElementById("search").value.trim().toLowerCase();
  const base = isTimeMachine ? currentMinisters : allMinisters;
  const filtered = q
    ? base.filter(m =>
        m.name.toLowerCase().includes(q) || m.title.toLowerCase().includes(q)
      )
    : base;
  renderCards(filtered, isTimeMachine ? document.getElementById("panel-title").textContent : undefined);
}

// ── Meta / status ─────────────────────────────────────────
function updateMeta(data) {
  document.getElementById("last-updated").textContent = data.last_updated
    ? `마지막 갱신: ${data.last_updated}`
    : "마지막 갱신: 알 수 없음";
}

function setStatus(state) {
  const dot = document.getElementById("status-dot");
  const txt = document.getElementById("status-text");
  dot.className = "dot";
  if (state === "live") { dot.classList.add("live"); txt.textContent = "실시간 모니터링 중"; }
  else if (state === "error") { dot.classList.add("error"); txt.textContent = "연결 오류"; }
  else { txt.textContent = "불러오는 중..."; }
}

// ── Countdown ─────────────────────────────────────────────
function tickCountdown() {
  countdown--;
  if (countdown <= 0) { countdown = 7 * 24 * 60 * 60; return; }
  const d = Math.floor(countdown / 86400);
  const h = Math.floor((countdown % 86400) / 3600);
  document.getElementById("stat-next").textContent = d > 0 ? `${d}일 ${h}시간` : `${h}시간`;
}

function resetCountdown() { countdown = 7 * 24 * 60 * 60; }

// ── Time Machine (slider) ─────────────────────────────────
function buildSlider() {
  const panel = document.getElementById("slider-panel");
  const slider = document.getElementById("time-slider");
  if (!snapshotMeta.length) return;

  slider.min = 0;
  slider.max = snapshotMeta.length - 1;
  slider.value = snapshotMeta.length - 1;

  const first = snapshotMeta[0].timestamp.slice(0, 10);
  const last = snapshotMeta[snapshotMeta.length - 1].timestamp.slice(0, 10);
  document.getElementById("slider-label-left").textContent = first;
  document.getElementById("slider-label-right").textContent = last;
  document.getElementById("slider-current-label").textContent = last;
}

function openTimeMachine() {
  if (!snapshotMeta.length) {
    showToast("저장된 스냅샷이 없습니다. 새로고침 후 다시 시도하세요.");
    return;
  }
  isTimeMachine = true;
  document.getElementById("slider-panel").style.display = "";
  // Show the most recent snapshot by default
  onSliderChange(snapshotMeta.length - 1);
}

function exitTimeMachine() {
  isTimeMachine = false;
  document.getElementById("slider-panel").style.display = "none";
  document.getElementById("search").value = "";
  currentMinisters = allMinisters;
  renderCards(allMinisters);
}

async function onSliderChange(val) {
  const idx = parseInt(val, 10);
  const meta = snapshotMeta[idx];
  if (!meta) return;

  document.getElementById("slider-current-label").textContent =
    meta.timestamp.slice(0, 10) + "  (" + meta.count + "명)";

  try {
    const res = await fetch(`/api/snapshot/${meta.index}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    currentMinisters = data.ministers || [];
    const label = `${meta.timestamp.slice(0, 10)} 당시 내각 구성원`;
    document.getElementById("search").value = "";
    renderCards(currentMinisters, label);
  } catch (err) {
    showToast("스냅샷 로드 실패: " + err.message);
  }
}

// ── Profile Modal ─────────────────────────────────────────
async function openProfile(idx) {
  const minister = currentMinisters[idx];
  if (!minister) return;

  // Populate static fields immediately
  document.getElementById("modal-name").textContent = minister.name;
  document.getElementById("modal-title").textContent = minister.title || "";
  document.getElementById("modal-appointed").textContent =
    minister.appointed ? `임명일: ${minister.appointed}` : "";

  const avatarWrap = document.getElementById("modal-avatar");
  if (minister.photo) {
    avatarWrap.innerHTML =
      `<img class="minister-avatar" src="${esc(minister.photo)}" alt="${esc(minister.name)}"
            onerror="this.replaceWith(makeAvatarEl('${esc(minister.name[0])}'))">`;
  } else {
    avatarWrap.innerHTML =
      `<div class="minister-avatar-placeholder">${esc(minister.name[0] || "?")}</div>`;
  }

  document.getElementById("modal-bio").innerHTML =
    `<div class="spinner" style="margin:0 auto"></div>`;
  document.getElementById("modal-wiki-link").style.display = "none";

  // Open modal
  document.getElementById("modal-backdrop").classList.add("open");
  document.getElementById("profile-modal").classList.add("open");

  // Fetch Wikipedia profile async
  try {
    const res = await fetch(`/api/profile?name=${encodeURIComponent(minister.name)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.thumbnail) {
      avatarWrap.innerHTML =
        `<img class="minister-avatar" src="${esc(data.thumbnail)}" alt="${esc(minister.name)}">`;
    }

    document.getElementById("modal-bio").textContent =
      data.summary || "위키피디아에 해당 인물 정보가 없습니다.";

    if (data.wiki_url) {
      const link = document.getElementById("modal-wiki-link");
      link.href = data.wiki_url;
      link.style.display = "inline-block";
    }
  } catch (err) {
    document.getElementById("modal-bio").textContent = "프로필 정보를 불러올 수 없습니다.";
  }
}

function closeModal() {
  document.getElementById("modal-backdrop").classList.remove("open");
  document.getElementById("profile-modal").classList.remove("open");
}

// Close modal on Escape key
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeModal();
});

// ── Toast ─────────────────────────────────────────────────
let toastTimer;
function showToast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3000);
}

// ── Util ──────────────────────────────────────────────────
function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/"/g, "&quot;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
