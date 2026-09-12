"""
hac_scraper.py

Talks to a district's Home Access Center (HAC) instance and pulls back
grade data. HAC is run by individual school districts on PowerSchool's
platform, so the exact HTML can vary slightly district to district —
the selectors below target the standard HAC MVC theme (the one used by
the large majority of districts as of 2026). If your district's HAC
looks different, you will likely need to tweak the CSS selectors in
`parse_classes()`.

No grades ever leave your own server: this module just performs the
same login + page-fetch a browser would, using the student's own HAC
credentials, and parses the HTML that comes back.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


class HACLoginError(Exception):
    """Raised when HAC rejects the username/password."""


class HACParseError(Exception):
    """Raised when the grades page doesn't look like what we expect."""


@dataclass
class Assignment:
    name: str
    category: str
    score: float | None       # None if not-yet-graded / excused
    points_possible: float | None
    date: str = ""


@dataclass
class Category:
    name: str
    weight: float | None      # percentage weight in the class, if HAC exposes it
    average: float | None


@dataclass
class CourseGrade:
    course_name: str
    teacher: str
    period: str
    average: float | None            # current overall average, 0-100
    categories: list[Category] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)


class HACClient:
    """
    One instance = one logged-in session against one district's HAC.

    Usage:
        client = HACClient(base_url="https://hac.yourdistrict.org/HomeAccess")
        client.login(username, password)
        grades = client.get_grades()
    """

    def __init__(self, base_url: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        })
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #

    def login(self, username: str, password: str) -> None:
        logon_url = f"{self.base_url}/Account/LogOn"

        resp = self.session.get(logon_url, timeout=self.timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        token_input = soup.find("input", {"name": "__RequestVerificationToken"})
        if not token_input:
            raise HACParseError(
                "Could not find the login form on this district's HAC site. "
                "Double check base_url points at the /HomeAccess root."
            )
        token = token_input.get("value", "")

        payload = {
            "__RequestVerificationToken": token,
            "LogOnDetails.UserName": username,
            "LogOnDetails.Password": password,
            "Database": "10",  # standard HAC "database" selector; usually fine as-is
        }

        resp = self.session.post(
            logon_url, data=payload, timeout=self.timeout, allow_redirects=True
        )
        resp.raise_for_status()

        if "Account/LogOn" in resp.url or "LogOnDetails" in resp.text:
            raise HACLoginError("HAC rejected that username/password.")

    # ------------------------------------------------------------------ #
    # Grades
    # ------------------------------------------------------------------ #

    def get_grades(self) -> list[CourseGrade]:
        """
        Fetches the Assignments page (per-class averages + category/assignment
        breakdown) and returns one CourseGrade per class.
        """
        url = f"{self.base_url}/Content/Student/Assignments.aspx"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return self._parse_classes(resp.text)

    def _parse_classes(self, html: str) -> list[CourseGrade]:
        soup = BeautifulSoup(html, "html.parser")

        # "Classwork Average" is the one piece of text confirmed present on
        # the real page (from your screenshot) regardless of the district's
        # specific CSS theme — so anchor on that instead of guessed class
        # names like the old ".AssignmentClass" selector, which don't exist
        # on Katy ISD's actual markup.
        avg_nodes = soup.find_all(string=re.compile(r"Classwork Average", re.I))

        if not avg_nodes:
            raise HACParseError(
                "Couldn't find any 'Classwork Average' labels on this page — "
                "the Assignments page may not have loaded, or this district's "
                "HAC uses different wording. Send the real page source (view-source) "
                "so the selectors can be corrected."
            )

        courses: list[CourseGrade] = []
        for i, avg_node in enumerate(avg_nodes):
            header_row = avg_node.find_parent(["tr", "div", "td"]) or avg_node.parent
            row_text = header_row.get_text(" ", strip=True)

            avg_match = re.search(r"Classwork Average\s*([\d.]+)", row_text, re.I)
            average = float(avg_match.group(1)) if avg_match else None

            # The course name is a link in the header row on the real page
            # (e.g. "0143A - 61 ENG 1 KAP/GT A"). Widen the search one level
            # up if the link isn't in the immediate row for some reason.
            link = header_row.find("a")
            if not link:
                wider = header_row.find_parent(["tr", "table", "div"])
                if wider:
                    link = wider.find("a")
                    if link:
                        header_row = wider
                        row_text = header_row.get_text(" ", strip=True)
                        avg_match = re.search(r"Classwork Average\s*([\d.]+)", row_text, re.I)

            if link and link.get_text(strip=True):
                title_text = link.get_text(strip=True)
            elif avg_match:
                title_text = row_text[:avg_match.start()].strip()
            else:
                title_text = row_text[:80].strip()

            course_name, teacher, period = self._split_header(title_text)

            # Safety net: never display something that still looks broken.
            if len(course_name) > 80 or re.search(r"Weighted|Percentage|Categor(y|ies)", course_name, re.I):
                continue

            # Scope the search for this course's tables to the document
            # region between this "Classwork Average" marker and the next
            # one (or the end of the page for the last course).
            next_avg_node = avg_nodes[i + 1] if i + 1 < len(avg_nodes) else None
            tables_in_section = []
            for el in avg_node.next_elements:
                if next_avg_node is not None and el is next_avg_node:
                    break
                if getattr(el, "name", None) == "table":
                    tables_in_section.append(el)

            categories, assignments = self._parse_section_tables(tables_in_section)

            courses.append(CourseGrade(
                course_name=course_name, teacher=teacher, period=period,
                average=average, categories=categories, assignments=assignments,
            ))

        if not courses:
            raise HACParseError(
                "Found 'Classwork Average' labels but couldn't extract a clean "
                "course name from any of them. Send the real page source so the "
                "header-parsing logic can be fixed for this district."
            )

        return courses

    @staticmethod
    def _parse_section_tables(tables) -> tuple[list["Category"], list["Assignment"]]:
        """
        Classifies each table found within one course's section as either the
        assignments table (has "Assignment"/"Score" columns) or the category
        breakdown table (has "Category"/"Weight" or a percent column), and
        parses rows accordingly. Column positions are read from each table's
        own header row rather than assumed, so extra/reordered columns in
        other districts' themes don't break this.
        """
        categories: list[Category] = []
        assignments: list[Assignment] = []

        for table in tables:
            rows = table.find_all("tr")
            if not rows:
                continue
            header_cells = [c.get_text(" ", strip=True) for c in rows[0].find_all(["td", "th"])]
            header_joined = " ".join(header_cells).lower()

            if "assignment" in header_joined and "score" in header_joined:
                col_index = {name.strip().lower(): idx for idx, name in enumerate(header_cells)}

                def get_col(cells, *names):
                    for n in names:
                        if n in col_index and col_index[n] < len(cells):
                            return cells[col_index[n]]
                    return None

                for row in rows[1:]:
                    cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
                    if len(cells) < 3:
                        continue
                    name = get_col(cells, "assignment")
                    if not name:
                        continue
                    category = get_col(cells, "category") or ""
                    score = HACClient._to_float(get_col(cells, "score"))
                    points = HACClient._to_float(get_col(cells, "total points", "points possible"))
                    assignments.append(Assignment(
                        name=name, category=category, score=score, points_possible=points,
                    ))
                continue

            # Not the assignments table — scan every row for the category
            # pattern (a plain name plus a percent figure) rather than relying
            # on the header row's wording, since real category summary tables
            # sometimes just have a plain "Categories" title with no column
            # labels rather than "Category"/"Weight" headers.
            for row in rows:
                cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
                if not cells:
                    continue
                name = cells[0]
                if not re.match(r"^[A-Za-z][A-Za-z \-]*$", name):
                    continue
                percent_idx = next((idx for idx, c in enumerate(cells) if "%" in c), None)
                if percent_idx is None:
                    continue
                average = HACClient._to_float(cells[percent_idx])
                weight = (
                    HACClient._to_float(cells[percent_idx + 1])
                    if percent_idx + 1 < len(cells) else None
                )
                categories.append(Category(name=name, weight=weight, average=average))

        return categories, assignments

    @staticmethod
    def _split_header(text: str) -> tuple[str, str, str]:
        # Different districts format this differently. Handle both:
        #   "Period 3 - Algebra II - J. Smith"   (3 parts: period, course, teacher)
        #   "0143A - 61 ENG 1 KAP/GT A"           (2 parts: section code, course)
        parts = [p.strip() for p in text.split(" - ")]
        if len(parts) >= 3:
            return parts[1], parts[2], parts[0]
        if len(parts) == 2:
            return parts[1], "", parts[0]
        return text, "", ""

    @staticmethod
    def _split_score(text: str) -> tuple[float | None, float | None]:
        m = re.match(r"([\d.]+)\s*/\s*([\d.]+)", text)
        if m:
            return float(m.group(1)), float(m.group(2))
        return None, None

    @staticmethod
    def _to_float(text: str) -> float | None:
        if not text:
            return None
        match = re.search(r"-?\d+(\.\d+)?", text.replace(",", ""))
        return float(match.group()) if match else None


def _round_half_up(x: float) -> int:
    # Python's built-in round() uses banker's rounding (round-half-to-even),
    # which can round 89.5 down to 88 instead of up to 90 depending on which
    # side is even. Always rounding .5 up matches what people expect from a
    # grade, and matches JS's Math.round() used on the frontend.
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


# Known HAC course names -> the display name you want instead. Matched
# case-insensitively after stripping the leading number HAC prepends
# (e.g. "61 ENG 1 KAP/GT A" -> "ENG 1 KAP/GT A" -> looked up here).
COURSE_NAME_OVERRIDES = {
    "ENG 1 KAP/GT A": "English 1 (KGT)",
    "ALG 2 KAP/GT A": "Algebra 2 (KGT)",
    "AP COMP SCI M A": "Computer Science A (AP)",
    "BIO KAP/GT A": "Biology (KGT)",
    "AP COMP SCI PRINC A": "Computer Science Principles (AP)",
    "TENNIS (SUBATH1)": "Tennis (A)",
    "SPAN 2 A": "Spanish 2 (A)",
    "MUS1ORCH": "Orchestra (A)",
}


def humanize_course_name(raw: str) -> str:
    """
    Cleans up a raw HAC course name for display:
    - looks it up in COURSE_NAME_OVERRIDES first (exact known renames)
    - otherwise strips the leading number HAC prepends, pulls out a tag
      (AP / KGT / K / DC / A) from the remaining words, and reformats as
      "{core name} ({tag})" — keeping the course name's own wording as-is
      rather than guessing an expansion for abbreviations we don't know.
    """
    raw = raw.strip()
    stripped = re.sub(r"^\d+\s+", "", raw).strip()

    for key, value in COURSE_NAME_OVERRIDES.items():
        if stripped.upper() == key.upper():
            return value

    tokens = stripped.split()
    if not tokens:
        return raw

    tag = None
    if tokens[0].upper() == "AP":
        tag = "AP"
        tokens = tokens[1:]
    else:
        upper_tokens = [t.upper() for t in tokens]
        if "KAP/GT" in upper_tokens:
            tag = "KGT"
            tokens.pop(upper_tokens.index("KAP/GT"))
        elif "KAP" in upper_tokens:
            tag = "K"
            tokens.pop(upper_tokens.index("KAP"))
        elif "DC" in upper_tokens:
            tag = "DC"
            tokens.pop(upper_tokens.index("DC"))

    # Drop a trailing lone "A" token — HAC's generic section filler — whether
    # or not another tag was already found above.
    if tokens and tokens[-1].upper() == "A":
        tokens.pop()

    if tag is None:
        tag = "A"

    core = " ".join(tokens).strip() or stripped
    return f"{core} ({tag})"


def letter_grade(average: float | None) -> str:
    if average is None:
        return "N/A"
    rounded = _round_half_up(average)
    if rounded >= 90:
        return "A"
    if rounded >= 80:
        return "B"
    if rounded >= 70:
        return "C"
    if rounded >= 60:
        return "D"
    return "F"


def what_if(category_averages: dict[str, float], category_weights: dict[str, float],
            hypothetical: dict[str, list[float]]) -> float:
    """
    Recomputes a weighted class average given hypothetical extra assignment
    scores (0-100) added into specific categories.

    category_averages: {"Tests": 88.0, "Homework": 95.0, ...}
    category_weights:  {"Tests": 50.0, "Homework": 20.0, ...}  (percent, sums ~100)
    hypothetical:       {"Tests": [92, 78], ...}  extra scores to fold in
    """
    weighted_sum = 0.0
    weight_total = 0.0
    for category, weight in category_weights.items():
        base_avg = category_averages.get(category)
        extra_scores = hypothetical.get(category, [])
        if base_avg is None and not extra_scores:
            continue
        scores = ([base_avg] if base_avg is not None else []) + extra_scores
        new_avg = statistics.mean(scores) if scores else 0.0
        weighted_sum += new_avg * weight
        weight_total += weight

    return round(weighted_sum / weight_total, 2) if weight_total else 0.0
