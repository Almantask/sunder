"""Static HTML review report with inline audio players."""

from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from sunder.classify import Classification, read_results_csv


def _src_for(audio_path: Path, report_path: Path) -> str:
    try:
        relative = Path(audio_path).resolve().relative_to(report_path.parent.resolve())
        return quote(relative.as_posix())
    except ValueError:
        relative = Path(audio_path).resolve()
        try:
            rel = Path(audio_path).resolve().relative_to(Path.cwd().resolve())
            return quote(rel.as_posix())
        except ValueError:
            return quote(relative.as_posix())


def render_report(
    rows: list[Classification],
    report_path: str | Path,
    *,
    title: str = "Ambience categorizer review",
) -> str:
    report_path = Path(report_path)
    by_category: dict[str, list[Classification]] = defaultdict(list)
    for row in rows:
        by_category[row.category].append(row)
    low = [row for row in rows if row.low_confidence]
    nav_items = []
    if low:
        nav_items.append(f'<a href="#needs-review">Needs review ({len(low)})</a>')
    for name in sorted(by_category, key=str.lower):
        nav_items.append(
            f'<a href="#cat-{html.escape(name)}">{html.escape(name)} ({len(by_category[name])})</a>'
        )

    sections = [ _summary(rows, low), _tracks_section("Needs review", "needs-review", low, report_path, flag_all=True) ]
    for name in sorted(by_category, key=str.lower):
        tracks = sorted(by_category[name], key=lambda row: (-row.confidence, row.path.name.lower()))
        sections.append(_tracks_section(name, f"cat-{name}", tracks, report_path))

    body = "\n".join(sections)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #12141a;
      --panel: #1b1f29;
      --line: #2c3342;
      --text: #e8ecf4;
      --muted: #9aa3b5;
      --warn: #f0b429;
      --ok: #3ecf8e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.45;
    }}
    header {{
      position: sticky; top: 0; z-index: 2;
      background: #0e1016;
      border-bottom: 1px solid var(--line);
      padding: 1rem 1.5rem;
    }}
    h1 {{ margin: 0 0 0.4rem; font-size: 1.25rem; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; }}
    nav a {{ color: #8ab4ff; text-decoration: none; font-size: 0.9rem; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 1rem 1.5rem 4rem; }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      margin: 1rem 0;
      padding: 1rem 1.1rem;
    }}
    h2 {{ margin: 0 0 0.8rem; font-size: 1.05rem; }}
    .meta {{ color: var(--muted); font-size: 0.9rem; }}
    .track {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 0.35rem 1rem;
      padding: 0.75rem 0;
      border-top: 1px solid var(--line);
    }}
    .track audio {{ width: 260px; height: 32px; }}
    .name {{ font-weight: 600; }}
    .flag {{
      display: inline-block;
      margin-left: 0.4rem;
      padding: 0.05rem 0.4rem;
      border-radius: 999px;
      background: #3a2a10;
      color: var(--warn);
      font-size: 0.75rem;
    }}
    .ok-flag {{ background: #163226; color: var(--ok); }}
    .no-flag {{ background: #3a1d1c; color: #e07a72; }}
    .ok {{ color: var(--ok); }}
    .warn {{ color: var(--warn); }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--line); }}
    input[type="search"] {{
      width: min(420px, 100%);
      margin-top: 0.6rem;
      padding: 0.45rem 0.7rem;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #10131a;
      color: var(--text);
    }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(title)}</h1>
    <nav>{"".join(nav_items)}</nav>
    <input id="filter" type="search" placeholder="Filter by filename or category">
  </header>
  <main>
    {body}
  </main>
  <script>
    const box = document.getElementById("filter");
    box.addEventListener("input", () => {{
      const q = box.value.toLowerCase().trim();
      document.querySelectorAll(".track").forEach((el) => {{
        const hay = (el.dataset.search || "").toLowerCase();
        el.style.display = !q || hay.includes(q) ? "" : "none";
      }});
    }});
  </script>
</body>
</html>
"""


def _summary(rows: list[Classification], low: list[Classification]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row.category] += 1
    table_rows = "\n".join(
        f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>"
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    )
    return f"""
    <section id="summary">
      <h2>Summary</h2>
      <p class="meta">{len(rows)} tracks · {len(counts)} categories ·
        <span class="warn">{len(low)} need review</span></p>
      <table>
        <thead><tr><th>Category</th><th>Tracks</th></tr></thead>
        <tbody>{table_rows}</tbody>
      </table>
    </section>
    """


def _tracks_section(
    title: str,
    anchor: str,
    rows: list[Classification],
    report_path: Path,
    flag_all: bool = False,
) -> str:
    if not rows:
        if flag_all:
            return f"""
    <section id="{html.escape(anchor)}">
      <h2>{html.escape(title)}</h2>
      <p class="meta">No low-confidence tracks.</p>
    </section>
    """
        return ""
    cards = []
    for row in rows:
        src = _src_for(row.path, report_path)
        flag = '<span class="flag">low confidence</span>' if row.low_confidence or flag_all else ""
        if row.review == "accepted":
            flag += '<span class="flag ok-flag">accepted</span>'
        elif row.review == "rejected":
            flag += '<span class="flag no-flag">rejected</span>'
        note = f'<div class="meta">Comment: {html.escape(row.comment)}</div>' if row.comment else ""
        search = html.escape(
            f"{row.path.name} {row.category} {row.runner_up} {row.matched_prompt} {row.comment} {row.review}",
            quote=True,
        )
        cards.append(
            f"""
      <div class="track" data-search="{search}">
        <div>
          <div class="name">{html.escape(row.path.name)}{flag}</div>
          <div class="meta">{html.escape(row.category)} · {row.confidence:.0%} confidence ·
            cosine {row.score:.3f} · runner-up {html.escape(row.runner_up)} ({row.runner_up_score:.3f})
            · “{html.escape(row.matched_prompt)}”</div>
          {note}
          <div class="meta">{html.escape(str(row.path))}</div>
        </div>
        <audio controls preload="none" src="{html.escape(src, quote=True)}"></audio>
      </div>
            """
        )
    return f"""
    <section id="{html.escape(anchor)}">
      <h2>{html.escape(title)} <span class="meta">({len(rows)})</span></h2>
      {"".join(cards)}
    </section>
    """


def write_report(
    results_csv: str | Path,
    out_html: str | Path,
) -> Path:
    rows = read_results_csv(results_csv)
    if not rows:
        raise RuntimeError(f"No rows in {results_csv}. Run classify first.")
    out_html = Path(out_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(render_report(rows, out_html), encoding="utf-8")
    print(f"Wrote {out_html.resolve()}", flush=True)
    return out_html
