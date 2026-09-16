function setFlash(message) {
  const el = document.getElementById("flash");
  if (!message) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = message;
}

// --- Client-side grade-shift tracking ---------------------------------
// The backend's local snapshot files don't reliably survive Render's free
// tier (its filesystem is wiped on every restart/spin-down), so "change
// since last login" is tracked here in the browser instead — this survives
// regardless of what the server does.

function snapshotKey(districtUrl, username) {
  return `ledgergrades_prev_avgs:${districtUrl}:${username}`;
}

function loadPreviousAverages(key) {
  try {
    return JSON.parse(localStorage.getItem(key) || "{}");
  } catch (err) {
    return {};
  }
}

function saveCurrentAverages(key, courses) {
  const snapshot = {};
  courses.forEach((c) => {
    if (c.average !== null && c.average !== undefined) snapshot[c.course_name] = c.average;
  });
  localStorage.setItem(key, JSON.stringify(snapshot));
}

function attachClientSideShifts(courses, districtUrl, username) {
  const key = snapshotKey(districtUrl, username);
  const previous = loadPreviousAverages(key);

  courses.forEach((c) => {
    const prevAvg = previous[c.course_name];
    if (prevAvg !== undefined && c.average !== null && c.average !== undefined) {
      c.shift = c.average - prevAvg;
    } else {
      c.shift = null;
    }
  });

  saveCurrentAverages(key, courses);
  return courses;
}

async function goToDashboard(courses, mode, username) {
  sessionStorage.setItem("ledgergrades_courses", JSON.stringify(courses));
  sessionStorage.setItem("ledgergrades_mode", mode);
  sessionStorage.setItem("ledgergrades_username", username);
  window.location.href = "dashboard.html";
}

function handleFetchError(err) {
  if (err.message.includes("timed out")) {
    setFlash(
      "The server never responded, even after retrying. If this only happens on " +
      "one network (like school wifi), that network is likely blocking access to " +
      "the backend's hosting domain — try a different network (e.g. cellular data) " +
      "to confirm."
    );
  } else if (err.message.includes("non-JSON") || err.message.includes("Failed to fetch")) {
    setFlash(
      "Couldn't reach the server after several tries. The backend may be waking up " +
      "from being idle (this can take up to a minute on the free hosting tier) — " +
      "please wait a moment and try again."
    );
  } else {
    setFlash(`Couldn't reach the API server (${err.message}).`);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("login-form");
  const loginBtn = document.getElementById("login-btn");
  const demoBtn = document.getElementById("demo-btn");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    setFlash(null);
    loginBtn.disabled = true;
    loginBtn.textContent = "Signing in…";

    const formData = new FormData(form);
    const body = {
      district_url: formData.get("district_url"),
      username: formData.get("username"),
      password: formData.get("password"),
    };

    try {
      const { ok, data } = await fetchJSON(`${API_BASE}/api/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }, {
        onRetry: () => { loginBtn.textContent = "Waking up the server…"; setFlash("The server was asleep — waking it up, this can take up to a minute."); },
      });

      if (!ok) {
        setFlash(data.error || "Something went wrong signing in.");
        return;
      }
      const courses = attachClientSideShifts(data.courses, body.district_url, body.username);
      setFlash(null);
      await goToDashboard(courses, "live", body.username);
    } catch (err) {
      handleFetchError(err);
    } finally {
      loginBtn.disabled = false;
      loginBtn.textContent = "Sign in";
    }
  });

  demoBtn.addEventListener("click", async () => {
    setFlash(null);
    demoBtn.disabled = true;
    demoBtn.textContent = "Loading…";
    try {
      const { ok, data } = await fetchJSON(`${API_BASE}/api/demo`, {}, {
        onRetry: () => { demoBtn.textContent = "Waking up the server…"; setFlash("The server was asleep — waking it up, this can take up to a minute."); },
      });
      if (!ok) {
        setFlash(data.error || "Couldn't load sample data.");
        return;
      }
      const courses = attachClientSideShifts(data.courses, "demo", "demo-student");
      setFlash(null);
      await goToDashboard(courses, "demo", "demo-student");
    } catch (err) {
      handleFetchError(err);
    } finally {
      demoBtn.disabled = false;
      demoBtn.textContent = "See it with sample grades";
    }
  });
});
