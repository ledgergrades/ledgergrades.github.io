function getVisitorId() {
  let id = localStorage.getItem("ledgergrades_visitor_id");
  if (!id) {
    id = (window.crypto && crypto.randomUUID)
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    localStorage.setItem("ledgergrades_visitor_id", id);
  }
  return id;
}

/**
 * Fetches JSON with automatic retries. The backend runs on Render's free
 * tier, which spins the server down after 15 minutes idle and takes about
 * a minute to wake back up — during that window it returns an HTML "waking
 * up" page instead of JSON, or the connection fails outright. This retries
 * a few times with a delay so a cold start doesn't look like a broken app,
 * and calls onRetry (if given) so the UI can show a "waking up" message.
 */
async function fetchJSON(url, options = {}, { retries = 3, delayMs = 5000, onRetry } = {}) {
  let lastErr;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const resp = await fetch(url, options);
      const contentType = resp.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        throw new Error("Server returned a non-JSON response (likely still waking up)");
      }
      const data = await resp.json();
      return { ok: resp.ok, status: resp.status, data };
    } catch (err) {
      lastErr = err;
      if (attempt === retries) break;
      if (onRetry) onRetry(attempt + 1, retries);
      await new Promise((res) => setTimeout(res, delayMs));
    }
  }
  throw lastErr;
}

function formatStatsDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

async function renderStats() {
  const panel = document.getElementById("stats-panel");
  if (!panel) return;

  try {
    const { ok, data } = await fetchJSON(`${API_BASE}/api/stats`, {}, { retries: 0 });
    if (!ok) return;

    const today = data.days[data.days.length - 1];
    document.getElementById("stats-today").textContent =
      `Today: ${today.views} view${today.views === 1 ? "" : "s"} (${today.uniques} unique)`;
    document.getElementById("stats-total").textContent =
      `All-time: ${data.total_views} views, ${data.total_uniques} unique`;

    const daysEl = document.getElementById("stats-days");
    daysEl.innerHTML = data.days.map((d) => `
      <div class="stats-day-row">
        <span>${formatStatsDate(d.date)}</span>
        <span>${d.views} view${d.views === 1 ? "" : "s"} · ${d.uniques} unique</span>
      </div>
    `).join("");

    panel.hidden = false;

    const toggle = document.getElementById("stats-toggle");
    if (toggle && !toggle.dataset.wired) {
      toggle.dataset.wired = "true";
      toggle.addEventListener("click", () => {
        const isHidden = daysEl.hidden;
        daysEl.hidden = !isHidden;
        toggle.textContent = isHidden ? "Hide" : "Last 7 days";
      });
    }
  } catch (err) {
    // Stats are a nice-to-have — never let a failed fetch break the page,
    // and never retry here (the page's own login/demo fetch already retries
    // and will wake the server if it's asleep).
  }
}

async function trackViewAndRenderStats() {
  try {
    await fetchJSON(`${API_BASE}/api/track-view`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visitor_id: getVisitorId() }),
    }, { retries: 0 });
  } catch (err) {
    // Ignore — tracking failures shouldn't block the page.
  }
  renderStats();
}

document.addEventListener("DOMContentLoaded", trackViewAndRenderStats);
