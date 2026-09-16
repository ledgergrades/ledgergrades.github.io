function letterGrade(avg) {
  if (avg === null || avg === undefined || isNaN(avg)) return "N/A";
  const rounded = Math.round(avg);
  if (rounded >= 90) return "A";
  if (rounded >= 80) return "B";
  if (rounded >= 70) return "C";
  if (rounded >= 60) return "D";
  return "F";
}

function fmt(n) {
  // Used only for the big course-average number — rounds to a whole number.
  return n === null || n === undefined ? "—" : Math.round(Number(n)).toString();
}

function fmt2(n) {
  // Used everywhere else (categories, assignments, what-if) — always shows
  // exactly 2 decimal places, e.g. 95 -> "95.00", 95.678 -> "95.68". This
  // only affects display; the underlying number is never rounded or
  // truncated before this point.
  return n === null || n === undefined ? "—" : Number(n).toFixed(2);
}

function mean(arr) {
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

function recomputeAverage(course, hypothetical) {
  let weightedSum = 0;
  let weightTotal = 0;

  course.categories.forEach((cat) => {
    const extra = hypothetical[cat.name] || [];
    const scores = [];
    if (cat.average !== null && cat.average !== undefined) scores.push(cat.average);
    scores.push(...extra);
    if (scores.length === 0 || cat.weight === null || cat.weight === undefined) return;

    const newAvg = mean(scores);
    weightedSum += newAvg * cat.weight;
    weightTotal += cat.weight;
  });

  return weightTotal ? weightedSum / weightTotal : null;
}

function shiftMarkup(course) {
  if (course.shift === null || course.shift === undefined) {
    return `<span class="shift na">first look</span>`;
  }
  // Classify with a tiny epsilon so float noise (e.g. 91.4 - 89.2 in binary
  // floating point) doesn't show a near-zero shift as "up" or "down" —
  // the stored/displayed value itself is never rounded, only compared.
  if (course.shift > 0.005) return `<span class="shift up">+${course.shift.toFixed(2)}</span>`;
  if (course.shift < -0.005) return `<span class="shift down">${course.shift.toFixed(2)}</span>`;
  return `<span class="shift flat">no change</span>`;
}

function categoryRowsMarkup(course) {
  return course.categories.map((cat) => `
    <tr>
      <td>${cat.name}</td>
      <td>${cat.weight !== null && cat.weight !== undefined ? cat.weight + "%" : "—"}</td>
      <td class="grade-${letterGrade(cat.average).toLowerCase()}">${fmt2(cat.average)}</td>
    </tr>
  `).join("");
}

function stripAsterisk(text) {
  return (text || "").replace(/\*/g, "").trim();
}

function assignmentRowsMarkup(course) {
  return (course.assignments || []).map((a) => `
    <tr>
      <td>${stripAsterisk(a.name)}</td>
      <td>${stripAsterisk(a.category) || "—"}</td>
      <td>${fmt2(a.score)}</td>
      <td>${fmt2(a.points_possible)}</td>
    </tr>
  `).join("");
}

function whatifRowsMarkup(course) {
  return course.categories.map((cat) => `
    <div class="whatif-row" data-category="${cat.name}">
      <span class="whatif-cat">${cat.name}</span>
      <input type="number" min="0" max="100" placeholder="score" class="whatif-input">
      <button type="button" class="whatif-add">Add</button>
      <span class="whatif-chips"></span>
    </div>
  `).join("");
}

function courseRowMarkup(course) {
  const letter = letterGrade(course.average);
  return `
    <section class="course-row grade-${letter.toLowerCase()}" data-course="${course.course_name}">
      <button class="course-summary" type="button" aria-expanded="false">
        <div class="course-id">
          <span class="course-name">${course.course_name}</span>
          <span class="course-meta">${course.teacher}${course.period ? " · Course: " + course.period : ""}</span>
        </div>
        <div class="course-shift">${shiftMarkup(course)}</div>
        <div class="course-average">
          <span class="letter-badge">${letter}</span>
          <span class="average-num">${fmt(course.average)}</span>
        </div>
      </button>

      <div class="course-detail">
        ${course.categories && course.categories.length ? `
          <table class="category-table">
            <thead><tr><th>Category</th><th>Weight</th><th>Average</th></tr></thead>
            <tbody>${categoryRowsMarkup(course)}</tbody>
          </table>

          ${course.assignments && course.assignments.length ? `
          <div class="assignments-toggle-wrap">
            <button type="button" class="btn-ghost small assignments-toggle" aria-expanded="false">
              Show individual grades
            </button>
            <div class="assignments-detail" hidden>
              <table class="assignment-table">
                <thead><tr><th>Name</th><th>Type</th><th>Grade</th><th>Out of</th></tr></thead>
                <tbody>${assignmentRowsMarkup(course)}</tbody>
              </table>
            </div>
          </div>
          ` : ``}

          <div class="whatif">
            <h3>What if…</h3>
            <p class="whatif-hint">Add a hypothetical score to a category and see the new average.</p>
            <div class="whatif-rows">${whatifRowsMarkup(course)}</div>
            <div class="whatif-result">
              <span>Projected average:</span>
              <strong class="whatif-projected">${fmt2(course.average)}</strong>
              <span class="whatif-letter"></span>
              <button type="button" class="btn-ghost small whatif-reset">Reset</button>
            </div>
          </div>
        ` : `<p class="no-detail">No category breakdown available for this class yet.</p>`}
      </div>
    </section>
  `;
}

function wireUpRow(row, courseByName) {
  const summaryBtn = row.querySelector(".course-summary");
  const courseName = row.dataset.course;
  const hypothetical = {};

  summaryBtn.addEventListener("click", () => {
    const isOpen = row.classList.toggle("open");
    summaryBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
  });

  const assignmentsToggle = row.querySelector(".assignments-toggle");
  const assignmentsDetail = row.querySelector(".assignments-detail");
  if (assignmentsToggle && assignmentsDetail) {
    assignmentsToggle.addEventListener("click", () => {
      const isHidden = assignmentsDetail.hidden;
      assignmentsDetail.hidden = !isHidden;
      assignmentsToggle.setAttribute("aria-expanded", isHidden ? "true" : "false");
      assignmentsToggle.textContent = isHidden ? "Hide individual grades" : "Show individual grades";
    });
  }

  row.querySelectorAll(".whatif-row").forEach((whatifRow) => {
    const category = whatifRow.dataset.category;
    const input = whatifRow.querySelector(".whatif-input");
    const addBtn = whatifRow.querySelector(".whatif-add");
    const chipsEl = whatifRow.querySelector(".whatif-chips");
    hypothetical[category] = [];

    const renderChips = () => {
      chipsEl.innerHTML = "";
      hypothetical[category].forEach((score, idx) => {
        const chip = document.createElement("span");
        chip.className = "whatif-chip";
        chip.textContent = `${score} ✕`;
        chip.title = "Click to remove";
        chip.style.cursor = "pointer";
        chip.addEventListener("click", () => {
          hypothetical[category].splice(idx, 1);
          renderChips();
          updateProjection();
        });
        chipsEl.appendChild(chip);
      });
    };

    const addScore = () => {
      const val = parseFloat(input.value);
      if (isNaN(val) || val < 0 || val > 100) return;
      hypothetical[category].push(val);
      input.value = "";
      renderChips();
      updateProjection();
    };

    addBtn.addEventListener("click", addScore);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addScore();
      }
    });
  });

  const projectedEl = row.querySelector(".whatif-projected");
  const letterEl = row.querySelector(".whatif-letter");
  const resetBtn = row.querySelector(".whatif-reset");

  function updateProjection() {
    const course = courseByName[courseName];
    if (!course) return;
    const projected = recomputeAverage(course, hypothetical);
    if (projected === null) {
      projectedEl.textContent = "—";
      letterEl.textContent = "";
      return;
    }
    projectedEl.textContent = fmt2(projected);
    letterEl.textContent = letterGrade(projected);
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      Object.keys(hypothetical).forEach((k) => (hypothetical[k] = []));
      row.querySelectorAll(".whatif-chips").forEach((el) => (el.innerHTML = ""));
      const course = courseByName[courseName];
      projectedEl.textContent = fmt2(course.average);
      letterEl.textContent = "";
    });
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const raw = sessionStorage.getItem("ledgergrades_courses");
  const mode = sessionStorage.getItem("ledgergrades_mode") || "live";
  const username = sessionStorage.getItem("ledgergrades_username") || "";

  const ledgerGradesBody = document.getElementById("ledger-grades-body");
  const emptyState = document.getElementById("empty-state");

  if (!raw) {
    emptyState.hidden = false;
    return;
  }

  const courses = JSON.parse(raw);
  document.getElementById("user-tag").textContent = username;
  if (mode === "demo") document.getElementById("demo-pill").hidden = false;

  document.getElementById("signout-link").addEventListener("click", () => {
    sessionStorage.clear();
  });

  const courseByName = Object.fromEntries(courses.map((c) => [c.course_name, c]));
  ledgerGradesBody.innerHTML = courses.map(courseRowMarkup).join("");
  ledgerGradesBody.querySelectorAll(".course-row").forEach((row) => wireUpRow(row, courseByName));
});
