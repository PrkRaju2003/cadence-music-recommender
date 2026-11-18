const $ = (s) => document.querySelector(s);
let user = 1,
  session = null,
  tracks = [],
  queue = [],
  current = null,
  source = "catalog",
  heard = 0,
  lastTime = 0,
  requestVersion = 0,
  toastTimer,
  playInFlight = false;
const audio = $("#audio");
audio.volume = 0.65;
const escapeHtml = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("#toast").hidden = true), 4500);
}
async function api(path, options = {}) {
  const r = await fetch("/api" + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(
      typeof e.detail === "string" ? e.detail : `Request failed (${r.status})`,
    );
  }
  return r.json();
}
function post(path, body) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}
function cover(t) {
  return `<div class="cover" style="--cover:${escapeHtml(t.color)}" aria-hidden="true"><span class="cover-numeral">CADENCE / ${String(t.album_id || t.id).padStart(2, "0")}</span><span class="cover-word">${escapeHtml(t.album || t.title)}</span><span class="cover-play">▶</span></div>`;
}
function showView(view) {
  document
    .querySelectorAll(".view")
    .forEach((el) => (el.hidden = el.id !== view));
  document.querySelectorAll(".nav").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === view);
    if (b.dataset.view === view) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  $("#view-label").textContent = {
    discover: "MADE FOR YOU",
    library: "THE CATALOG",
    insights: "LISTENING LAB",
  }[view];
  window.scrollTo({ top: 0, behavior: "instant" });
  if (view === "insights") loadInsights().catch((e) => toast(e.message));
}
document
  .querySelectorAll("[data-view]")
  .forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
async function refreshRecommendations() {
  const version = ++requestVersion;
  const activeUser = user;
  $("#refresh").disabled = true;
  try {
    const context = current ? `&context_track=${current.id}` : "";
    const [rec, albums] = await Promise.all([
      api(`/recommendations/${activeUser}?limit=6${context}`),
      api(`/recommendations/${activeUser}?kind=album&limit=4${context}`),
    ]);
    if (version !== requestVersion) return;
    $("#recommendation-grid").innerHTML = rec.items
      .map(
        (t) =>
          `<button class="album-card" data-track="${t.id}" aria-label="Play ${escapeHtml(t.title)} by ${escapeHtml(t.artist)}">${cover(t)}<div class="album-meta"><div><h3>${escapeHtml(t.title)}</h3><p>${escapeHtml(t.artist)}</p></div><span>${escapeHtml(t.genre)}</span></div><p class="reason">${escapeHtml(t.reason)}</p></button>`,
      )
      .join("");
    $("#recommendation-grid")
      .querySelectorAll("[data-track]")
      .forEach((b) =>
        b.addEventListener("click", () =>
          play(
            Number(b.dataset.track),
            "recommendation",
            rec.items.map((t) => t.id),
          ),
        ),
      );
    $("#album-recommendations").innerHTML = albums.items
      .map(
        (a) =>
          `<button class="album-pick" data-album="${a.id}" aria-label="Play album ${escapeHtml(a.title)}">${cover(a)}<div><h3>${escapeHtml(a.title)}</h3><p>${escapeHtml(a.artist)}</p></div><span>↗</span></button>`,
      )
      .join("");
    $("#album-recommendations")
      .querySelectorAll("[data-album]")
      .forEach((b) =>
        b.addEventListener("click", () => {
          const list = tracks
            .filter((t) => t.album_id === Number(b.dataset.album))
            .map((t) => t.id);
          play(list[0], "recommendation", list);
        }),
      );
  } finally {
    if (version === requestVersion) $("#refresh").disabled = false;
  }
}
$("#refresh").addEventListener("click", () =>
  refreshRecommendations().catch((e) => toast(e.message)),
);
$("#explain-toggle").addEventListener("click", () => {
  const open = !$("#explanation").hidden;
  $("#explanation").hidden = open;
  $("#explain-toggle").setAttribute("aria-expanded", String(!open));
});
function renderCatalog() {
  const query = $("#search").value.toLowerCase(),
    genre = $("#genre-filter").value;
  const filtered = tracks.filter(
    (t) =>
      (!genre || t.genre === genre) &&
      `${t.title} ${t.artist} ${t.album}`.toLowerCase().includes(query),
  );
  $("#catalog-list").innerHTML = filtered.length
    ? filtered
        .map(
          (t, i) =>
            `<button class="track-row" data-track="${t.id}" aria-label="Play ${escapeHtml(t.title)}"><span>${String(i + 1).padStart(2, "0")}</span><span class="track-info"><span class="track-mini" style="--cover:${escapeHtml(t.color)}">♪</span><span><b>${escapeHtml(t.title)}</b><small>${escapeHtml(t.artist)}</small></span></span><span class="track-album">${escapeHtml(t.album)}</span><span class="genre-pill">${escapeHtml(t.genre)}</span><span>0:12</span></button>`,
        )
        .join("")
    : '<p class="empty">No tracks match. Try another search.</p>';
  $("#catalog-list")
    .querySelectorAll("[data-track]")
    .forEach((b) =>
      b.addEventListener("click", () =>
        play(
          Number(b.dataset.track),
          "catalog",
          filtered.map((t) => t.id),
        ),
      ),
    );
}
$("#search").addEventListener("input", renderCatalog);
$("#genre-filter").addEventListener("change", renderCatalog);
async function flush() {
  if (!current || !session || heard < 0.15) return;
  const event = {
    session_id: session,
    track_id: current.id,
    played_ms: Math.min(current.duration_ms, Math.round(heard * 1000)),
    source,
    event_key: crypto.randomUUID(),
  };
  heard = 0;
  try {
    await post("/playback", event);
  } catch (e) {
    toast("Listening event could not be saved: " + e.message);
  }
}
async function play(id, origin = "catalog", ids = tracks.map((t) => t.id)) {
  if (playInFlight) return;
  playInFlight = true;
  try {
    audio.pause();
    await flush();
    if (!session) session = (await post("/sessions", { user_id: user })).id;
    current = tracks.find((t) => t.id === id);
    if (!current) throw new Error("Track not found");
    source = origin;
    queue = ids;
    heard = 0;
    lastTime = 0;
    audio.src = `/media/${id}`;
    $("#now-title").textContent = current.title;
    $("#now-artist").textContent = `${current.artist} · ${current.album}`;
    $("#player-art").style.background = current.color;
    $("#player-art").textContent = "♪";
    $("#playing-source").textContent =
      origin === "recommendation"
        ? "FROM YOUR RECOMMENDATIONS"
        : "FROM THE CATALOG";
    await audio.play();
  } catch (e) {
    toast(e.message);
  } finally {
    playInFlight = false;
  }
}
$("#play-pause").addEventListener("click", () => {
  if (!current) {
    if (tracks.length) play(tracks[0].id);
    return;
  }
  if (audio.paused) audio.play().catch((e) => toast(e.message));
  else audio.pause();
});
function advance(direction) {
  if (!tracks.length) return;
  const ids = queue.length ? queue : tracks.map((t) => t.id);
  let index = current ? ids.indexOf(current.id) : -1;
  play(ids[(index + direction + ids.length) % ids.length], source, ids);
}
$("#next").addEventListener("click", () => advance(1));
$("#prev").addEventListener("click", () => advance(-1));
audio.addEventListener("ended", () => advance(1));
audio.addEventListener("play", () => {
  $("#play-pause").textContent = "Ⅱ";
  $("#play-pause").setAttribute("aria-label", "Pause");
});
audio.addEventListener("pause", () => {
  $("#play-pause").textContent = "▶";
  $("#play-pause").setAttribute("aria-label", "Play");
});
audio.addEventListener("error", () =>
  toast("Audio unavailable. Run the seed command to generate demo audio."),
);
audio.addEventListener("timeupdate", () => {
  const dt = audio.currentTime - lastTime;
  if (dt > 0 && dt < 2 && !audio.seeking) heard += dt;
  lastTime = audio.currentTime;
  $("#seek").value = audio.currentTime;
  $("#current-time").textContent =
    `0:${String(Math.floor(audio.currentTime)).padStart(2, "0")}`;
});
audio.addEventListener("seeked", () => (lastTime = audio.currentTime));
$("#seek").addEventListener("input", () => {
  if (current) {
    audio.currentTime = Number($("#seek").value);
    lastTime = audio.currentTime;
  }
});
$("#volume").addEventListener(
  "input",
  () => (audio.volume = Number($("#volume").value)),
);
$("#listener").addEventListener("change", async () => {
  try {
    audio.pause();
    await flush();
    user = Number($("#listener").value);
    session = null;
    current = null;
    audio.removeAttribute("src");
    $("#now-title").textContent = "A fresh perspective.";
    $("#now-artist").textContent = "Pick a track for this listener";
    await refreshRecommendations();
  } catch (e) {
    toast(e.message);
  }
});
async function loadInsights() {
  const [data, evaluation] = await Promise.all([
    api("/analytics"),
    api("/evaluation"),
  ]);
  const t = data.totals;
  $("#kpis").innerHTML = [
    ["TOTAL PLAYS", t.plays.toLocaleString(), "Synthetic seed + demo events"],
    [
      "LISTENING MINUTES",
      Number(t.listening_minutes || 0).toLocaleString(),
      "Actual recorded playback time",
    ],
    [
      "COMPLETION",
      `${t.completion_pct || 0}%`,
      "Average fraction of track played",
    ],
    ["SKIP RATE", `${t.skip_pct || 0}%`, "A skip is less than 30% played"],
  ]
    .map(
      ([label, value, note]) =>
        `<article class="kpi"><p>${label}</p><strong>${value}</strong><small>${note}</small></article>`,
    )
    .join("");
  const daily = data.daily,
    max = Math.max(...daily.map((d) => d.plays), 1);
  const points = daily
    .map(
      (d, i) =>
        `${10 + (i * 480) / Math.max(daily.length - 1, 1)},${140 - (d.plays / max) * 120}`,
    )
    .join(" ");
  $("#activity-chart").innerHTML =
    `<svg viewBox="0 0 500 155" role="img" aria-label="Daily play counts range from ${Math.min(...daily.map((d) => d.plays), 0)} to ${max}"><path d="M10 140H490M10 80H490M10 20H490" stroke="#20282015" fill="none"/><polyline points="${points}" fill="none" stroke="#82996d" stroke-width="3" stroke-linejoin="round"/></svg><div class="chart-labels"><span>${daily[0]?.play_date || "No events"}</span><span>${daily.at(-1)?.play_date || ""}</span></div>`;
  $("#genre-chart").innerHTML = data.genres
    .map(
      (g) =>
        `<div class="genre-bar"><div><span>${escapeHtml(g.genre)}</span><span>${g.plays.toLocaleString()} plays</span></div><div><i style="width:${t.plays ? (g.plays / t.plays) * 100 : 0}%"></i></div></div>`,
    )
    .join("");
  $("#evaluation-body").innerHTML = evaluation.results
    .map(
      (r) =>
        `<tr class="${r.strategy === "hybrid" ? "hybrid" : ""}"><td>${r.strategy}</td><td>${(r.hit_rate * 100).toFixed(1)}%</td><td>${r.ndcg.toFixed(3)}</td><td>${r.mrr.toFixed(3)}</td><td>${(r.catalog_coverage * 100).toFixed(1)}%</td></tr>`,
    )
    .join("");
}
$("#refresh-insights").addEventListener("click", () =>
  loadInsights().catch((e) => toast(e.message)),
);
// Keep initialization explicit so failure states are visible rather than silently empty.
async function start() {
  try {
    const [catalog, users, genres] = await Promise.all([
      api("/catalog"),
      api("/users"),
      api("/genres"),
    ]);
    tracks = catalog;
    if (!users.length)
      throw new Error("Run python -m cadence.seed to create the demo catalog.");
    user = users[0].id;
    $("#listener").innerHTML = users
      .map(
        (u) => `<option value="${u.id}">${escapeHtml(u.display_name)}</option>`,
      )
      .join("");
    genres.forEach((g) => {
      const option = document.createElement("option");
      option.value = g.name;
      option.textContent = g.name;
      $("#genre-filter").append(option);
    });
    renderCatalog();
    await refreshRecommendations();
  } catch (e) {
    toast(e.message);
    $("#recommendation-grid").innerHTML =
      '<p class="empty">Could not load your mix. Check the API and seed data, then refresh.</p>';
  }
}
start();

window.addEventListener("pagehide", () => {
  if (!current || !session || heard < 0.15) return;
  const payload = {
    session_id: session,
    track_id: current.id,
    played_ms: Math.min(current.duration_ms, Math.round(heard * 1000)),
    source,
    event_key: crypto.randomUUID(),
  };
  navigator.sendBeacon(
    "/api/playback",
    new Blob([JSON.stringify(payload)], { type: "application/json" }),
  );
  heard = 0;
});
