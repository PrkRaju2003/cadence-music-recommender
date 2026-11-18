// Confirmation completes in Supabase; sign in normally after returning.
if (
  location.hash.includes("access_token=") ||
  location.hash.includes("refresh_token=")
)
  history.replaceState(null, "", location.pathname + location.search);
const API_PREFIX = location.pathname.startsWith("/demo") ? "/demo" : "";
const $ = (s) => document.querySelector(s);
let appMode = "demo",
  authMode = "login",
  refreshPromise = null,
  sqlReports = [];
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
let playKey = null,
  progressBusy = false,
  pendingProgress = new Map();
const guestPlays = new Map();
let insightBusy = false;
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
  const r = await fetch(API_PREFIX + "/api" + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (
    r.status === 401 &&
    appMode === "supabase" &&
    !path.startsWith("/auth/") &&
    !options._retried
  ) {
    try {
      if (!refreshPromise)
        refreshPromise = post("/auth/refresh", {}).finally(() => {
          refreshPromise = null;
        });
      await refreshPromise;
      return api(path, { ...options, _retried: true });
    } catch (error) {
      gate(true);
      throw error;
    }
  }
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
    sql: "SQL STUDIO",
  }[view];
  window.scrollTo({ top: 0, behavior: "instant" });
  if (view === "insights") loadInsights().catch((e) => toast(e.message));
  if (view === "sql") loadSqlReports().catch((e) => toast(e.message));
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
function progressEvent() {
  if (!current || !session || heard < 0.15) return null;
  return {
    session_id: session,
    track_id: current.id,
    played_ms: Math.min(current.duration_ms, Math.round(heard * 1000)),
    source,
    event_key: playKey,
  };
}
async function flush() {
  const event = progressEvent();
  if (event) {
    if (appMode === "showcase")
      guestPlays.set(event.event_key, {
        ...event,
        genre: current.genre,
        duration_ms: current.duration_ms,
        date: new Date().toISOString().slice(0, 10),
      });
    else pendingProgress.set(event.event_key, event);
  }
  if (appMode === "showcase") return;
  // Failed requests stay queued. A retry uses the same key and cumulative time.
  if (progressBusy) return;
  progressBusy = true;
  try {
    for (const [key, payload] of pendingProgress) {
      await post(
        appMode === "supabase" ? "/playback/progress" : "/playback",
        payload,
      );
      if (pendingProgress.get(key) === payload) pendingProgress.delete(key);
      if (appMode === "demo" && playKey === key) {
        heard = 0;
        playKey = crypto.randomUUID();
      }
    }
  } catch (e) {
    toast("Listening progress is waiting to sync: " + e.message);
  } finally {
    progressBusy = false;
  }
}
function guestAnalytics(data) {
  if (appMode !== "showcase") return data;
  const events = [...guestPlays.values()],
    t = data.totals,
    count = events.length;
  const original = t.plays;
  t.plays += count;
  t.listening_minutes = Number(
    (
      Number(t.listening_minutes) +
      events.reduce((n, e) => n + e.played_ms, 0) / 60000
    ).toFixed(2),
  );
  if (count) {
    t.completion_pct = (
      (original * t.completion_pct +
        events.reduce((n, e) => n + (100 * e.played_ms) / e.duration_ms, 0)) /
      t.plays
    ).toFixed(1);
    t.skip_pct = (
      (original * t.skip_pct +
        events.filter((e) => e.played_ms / e.duration_ms < 0.3).length * 100) /
      t.plays
    ).toFixed(1);
  }
  for (const e of events) {
    let day = data.daily.find((d) => d.play_date === e.date);
    if (!day) {
      day = { play_date: e.date, plays: 0 };
      data.daily.push(day);
    }
    day.plays++;
    let genre = data.genres.find((g) => g.genre === e.genre);
    if (!genre) {
      genre = { genre: e.genre, plays: 0 };
      data.genres.push(genre);
    }
    genre.plays++;
  }
  data.daily.sort((a, b) => a.play_date.localeCompare(b.play_date));
  return data;
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
    playKey = crypto.randomUUID();
    lastTime = 0;
    audio.src = `${API_PREFIX}/media/${id}`;
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
  const [rawData, evaluation] = await Promise.all([
    api("/analytics"),
    api("/evaluation"),
  ]);
  const data = guestAnalytics(rawData);
  const t = data.totals;
  $("#kpis").innerHTML = [
    [
      "TOTAL PLAYS",
      t.plays.toLocaleString(),
      appMode === "supabase"
        ? "Your activity · updates every 5 seconds"
        : appMode === "showcase"
          ? "Sample data + plays in this tab"
          : "Synthetic seed + demo events",
    ],
    [
      "LISTENING MINUTES",
      Number(t.listening_minutes || 0).toLocaleString(),
      "Actual recorded playback time",
    ],
    [
      "COMPLETION",
      `${t.completion_pct || 0}%`,
      "Average heard so far · live progress",
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
async function loadApp() {
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
    $("#genre-filter").innerHTML = '<option value="">All genres</option>';
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

// Heartbeat and visible dashboard refresh are bounded; no background polling.
setInterval(async () => {
  if (document.hidden) return;
  if (!audio.paused && appMode !== "demo") await flush();
  else if (pendingProgress.size) await flush();
  if (
    !$("#insights").hidden &&
    !insightBusy &&
    !document.body.classList.contains("auth-gated")
  ) {
    insightBusy = true;
    try {
      await loadInsights();
    } catch (e) {
      toast(e.message);
    } finally {
      insightBusy = false;
    }
  }
}, 5000);
audio.addEventListener("pause", () => {
  if (appMode !== "demo") flush();
});
window.addEventListener("pagehide", () => {
  const event = progressEvent();
  if (appMode === "showcase") return;
  if (event) pendingProgress.set(event.event_key, event);
  for (const payload of pendingProgress.values())
    navigator.sendBeacon(
      API_PREFIX +
        "/api" +
        (appMode === "supabase" ? "/playback/progress" : "/playback"),
      new Blob([JSON.stringify(payload)], { type: "application/json" }),
    );
});

function gate(show) {
  $("#auth-screen").hidden = !show;
  document
    .querySelectorAll("aside,main,.player")
    .forEach((el) => (el.inert = show));
  document.body.classList.toggle("auth-gated", show);
}
function setAuthMode(mode) {
  authMode = mode;
  document.querySelectorAll("[data-auth-mode]").forEach((b) => {
    const on = b.dataset.authMode === mode;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", String(on));
  });
  $("#name-field").hidden = mode !== "signup";
  $("#favorite-field").hidden = mode !== "signup";
  $("#auth-name").required = mode === "signup";
  $("#auth-password").autocomplete =
    mode === "signup" ? "new-password" : "current-password";
  $("#auth-title").textContent =
    mode === "signup" ? "Find your own rhythm." : "Good to have you back.";
  $("#auth-subtitle").textContent =
    mode === "signup"
      ? "Create a space for your listening journey."
      : "Sign in to pick up where you left off.";
  $("#auth-submit").textContent =
    mode === "signup" ? "Create account ↗" : "Sign in ↗";
  $("#auth-message").textContent = "";
}
document
  .querySelectorAll("[data-auth-mode]")
  .forEach((b) =>
    b.addEventListener("click", () => setAuthMode(b.dataset.authMode)),
  );
async function signedIn() {
  let account;
  try {
    account = await api("/auth/session");
  } catch (error) {
    try {
      await post("/auth/refresh", {});
      account = await api("/auth/session");
    } catch {
      gate(true);
      return;
    }
  }
  $("#account-name").textContent = account.user.display_name;
  $("#account-menu").hidden = false;
  $(".listener-label").hidden = true;
  const banner = $(".demo-banner");
  banner.innerHTML =
    'Original demo audio. Your listening activity is saved privately to your account. <a href="/docs" target="_blank">API reference ↗</a>';
  $("#insights .page-title .fineprint").textContent =
    "Only your account’s listening activity is shown here. Offline evaluation uses synthetic seed data.";
  const exportLink = $("#insights .bi-note>a");
  exportLink.href = "/api/export";
  exportLink.textContent = "Download my CSVs ↗";
  exportLink.removeAttribute("target");
  gate(false);
  await loadApp();
}
$("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#auth-submit");
  button.disabled = true;
  $("#auth-message").textContent = "";
  const body = {
    email: $("#auth-email").value.trim(),
    password: $("#auth-password").value,
  };
  if (authMode === "signup")
    Object.assign(body, {
      display_name: $("#auth-name").value.trim(),
      genre_id: Number($("#auth-genre").value),
    });
  try {
    const result = await post("/auth/" + authMode, body);
    $("#auth-password").value = "";
    if (result.signed_in) await signedIn();
    else {
      setAuthMode("login");
      $("#auth-message").textContent = result.message;
    }
  } catch (error) {
    $("#auth-message").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
$("#sign-out").addEventListener("click", async () => {
  try {
    audio.pause();
    await flush();
    await post("/auth/logout", {});
    pendingProgress.clear();
    heard = 0;
    session = null;
    current = null;
    audio.removeAttribute("src");
    $("#recommendation-grid").innerHTML = "";
    $("#sql-results").innerHTML = "";
    $("#kpis").innerHTML = "";
    $("#account-menu").hidden = true;
    gate(true);
    setAuthMode("login");
  } catch (error) {
    toast(error.message);
  }
});
async function loadSqlReports() {
  if (!sqlReports.length) {
    sqlReports = await api("/sql/queries");
    $("#sql-report").innerHTML = sqlReports
      .map((r) => `<option value="${r.id}">${escapeHtml(r.name)}</option>`)
      .join("");
  }
  updateSqlPreview();
}
function updateSqlPreview() {
  const report = sqlReports.find((r) => r.id === $("#sql-report").value);
  if (report) $("#sql-preview").textContent = report.sql;
}
$("#sql-report").addEventListener("change", updateSqlPreview);
$("#run-sql").addEventListener("click", async () => {
  const button = $("#run-sql");
  button.disabled = true;
  try {
    const result = await post("/sql/run", {
      report_id: $("#sql-report").value,
      limit: 20,
      ...(appMode === "showcase" ? { user_id: user } : {}),
    });
    $("#sql-meta").textContent =
      `${result.row_count} rows · ${result.database}`;
    $("#sql-results").innerHTML = result.rows.length
      ? `<div class="sql-table-scroll"><table><thead><tr>${result.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead><tbody>${result.rows.map((row) => `<tr>${result.columns.map((c) => `<td>${escapeHtml(row[c] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
      : '<p class="empty">No listening activity yet. Play a track, then try this report again.</p>';
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});
async function start() {
  try {
    const config = await api("/config");
    appMode = config.mode;
    if (appMode === "showcase") {
      $(".demo-banner").innerHTML =
        'Live demo · sample data + your plays in this tab · refreshes every 5s. Guest activity resets on reload; SQL reports use sample data. <a href="/">Create an account to save your journey ↗</a>';
    }
    if (config.auth_required) await signedIn();
    else await loadApp();
  } catch (error) {
    toast(error.message);
  }
}
start();
