"""
File: Cully/modules/report.py
Description: Writes an HTML report of the current pipeline results, grouped by event then burst.
Each burst shows its candidates in a green Keep group, with the rest and unranked photos alongside. Thumbnails are
cached by image hash, so later reports only make thumbnails for new photos.
Run from Cully/modules (either venv):
    python report.py [--catalog PATH] [--out DIR] [--open]
Author: Miguel Macias
Date: 2026-11-16
"""

import argparse
import html
import webbrowser
from collections import defaultdict
from datetime import datetime
from pathlib import Path


from utils.make_thumbnail import make_thumbnail
from config.config import Config
from config.settings import Settings
from models.catalog import Catalog
from models.report_photo import ReportPhoto

def short_time(iso: str | None) -> str:
    if iso is None:
        return "unknown time"
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M:%S")


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' * (n != 1)}"


def photo_card(photo: ReportPhoto, thumbs_ok: set[str]) -> str:
    """One thumbnail with its badges."""
    path = Path(photo.image_path)
    badges = []
    if photo.is_candidate:
        badges.append('<span class="badge good">&#10003; Candidate</span>')
    if photo.rank is not None:
        badges.append(f'<span class="badge rank">#{photo.rank}</span>')
        badges.append(f'<span class="badge">{photo.score:.2f}</span>')
    if photo.eyes_open is False:
        badges.append('<span class="badge bad">Eyes closed</span>')
    if photo.unranked_reason:
        badges.append(f'<span class="badge muted">{html.escape(photo.unranked_reason)}</span>')

    if photo.image_hash in thumbs_ok:
        image = f'<img src="thumbs/{photo.image_hash}.jpg" alt="{html.escape(path.name)}" loading="lazy">'
    else:
        image = '<div class="missing">Can\'t read file</div>'

    classes = ["card"]
    if photo.is_candidate:
        classes.append("candidate")
    if photo.rank is None:
        classes.append("unranked")
    # Old catalogs can hold relative paths, which can't be linked; rescanning the folder fixes them
    if path.is_absolute():
        image = f'<a href="{path.as_uri()}" target="_blank" title="{html.escape(str(path))}">{image}</a>'
    return f"""
          <figure class="{' '.join(classes)}">
            {image}
            <figcaption>
              <div class="badges">{''.join(badges)}</div>
              <div class="name">{html.escape(path.name)}</div>
            </figcaption>
          </figure>"""


def lane(kind: str, label: str, photos: list[ReportPhoto], thumbs_ok: set[str]) -> str:
    """A labelled group of cards inside a burst (candidates, rest or unranked)."""
    if not photos:
        return ""
    cards = "".join(photo_card(p, thumbs_ok) for p in photos)
    return f"""
        <div class="lane {kind}">
          <div class="lane-label">{label} <span>{len(photos)}</span></div>
          <div class="cards">{cards}</div>
        </div>"""


def burst_block(number: int, photos: list[ReportPhoto], thumbs_ok: set[str]) -> str:
    """One burst: candidates first, the rest alongside, then unranked."""
    candidates = [p for p in photos if p.is_candidate]
    rest = [p for p in photos if p.rank is not None and not p.is_candidate]
    unranked = [p for p in photos if p.rank is None]
    status = plural(len(candidates), "candidate") if candidates else "not ranked"
    lanes = (
        lane("keep", "Keep", candidates, thumbs_ok)
        + lane("rest", "Rest", rest, thumbs_ok)
        + lane("unranked", "Unranked", unranked, thumbs_ok)
    )
    return f"""
      <section class="burst{' has-candidate' if candidates else ''}">
        <header><h3>Burst {number}</h3>
          <span class="meta">{short_time(photos[0].burst_start)[11:]} · {plural(len(photos), "photo")} · {status}</span></header>
        <div class="lanes">{lanes}
        </div>
      </section>"""


def group_by(photos: list[ReportPhoto], key) -> dict:
    """Groups photos by key, keeping their order."""
    groups: dict = defaultdict(list)
    for photo in photos:
        groups[key(photo)].append(photo)
    return groups


def event_block(number: int | None, photos: list[ReportPhoto], thumbs_ok: set[str], first_burst: int) -> tuple[str, int]:
    """One event with its bursts. Returns the html and the next burst number."""
    bursts = group_by(photos, lambda p: p.burst_id)
    blocks = []
    for offset, burst_photos in enumerate(bursts.values()):
        blocks.append(burst_block(first_burst + offset, burst_photos, thumbs_ok))
    n_cand = sum(p.is_candidate for p in photos)
    if number is None:
        title = "No capture time"
        meta = f"{plural(len(photos), 'photo')} · can't be grouped into bursts"
        # No bursts here, so show them as one unranked group
        blocks = [f"""
      <section class="burst">
        <div class="lanes">{lane("unranked", "Unranked", photos, thumbs_ok)}
        </div>
      </section>"""]
    else:
        first = photos[0]
        start, end = short_time(first.event_start), short_time(first.event_end)
        if start == end:
            span = start
        elif start[:10] == end[:10]:
            span = f"{start} – {end[11:]}"
        else:
            span = f"{start} – {end}"
        meta = (f"{span} · {html.escape(first.camera_model or 'unknown camera')} · "
                f"{plural(len(bursts), 'burst')} · {plural(len(photos), 'photo')} · {plural(n_cand, 'candidate')}")
        title = f"Event {number}"
    return f"""
    <section class="event{' has-candidate' if n_cand else ''}">
      <header class="event-head"><h2>{title}</h2><span class="meta">{meta}</span></header>
      <div class="bursts">{''.join(blocks)}
      </div>
    </section>""", first_burst + len(bursts)


def build_html(photos: list[ReportPhoto], thumbs_ok: set[str], catalog_path: str) -> str:
    events = group_by(photos, lambda p: p.event_id)  # already in event, burst, rank order

    ranked = [p for p in photos if p.rank is not None]
    candidates = sum(p.is_candidate for p in photos)
    closed = sum(p.eyes_open is False for p in ranked)
    n_events = sum(1 for key in events if key is not None)
    n_bursts = len({p.burst_id for p in photos if p.burst_id is not None})

    sections = []
    burst_number = 1
    event_number = 1
    for event_id, group in events.items():
        if event_id is None:
            block, _ = event_block(None, group, thumbs_ok, 0)
        else:
            block, burst_number = event_block(event_number, group, thumbs_ok, burst_number)
            event_number += 1
        sections.append(block)

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cully Report</title>
<style>
  :root {{
    --bg: #f6f6f4; --surface: #ffffff; --text: #1d1d1b; --muted: #6b6b66; --border: #e2e2dd;
    --event-bg: #ffffff; --burst-bg: #f6f6f4;
    --good: #1f7a3d; --good-bg: #e3f3e8; --good-lane: #f0f9f3; --bad: #b42318; --bad-bg: #fde8e6;
    --rank: #1d4ed8; --rank-bg: #e3ebfd; --chip-bg: #efefeb;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #161615; --surface: #20201e; --text: #ececea; --muted: #9a9a94; --border: #33332f;
      --event-bg: #1c1c1a; --burst-bg: #232321;
      --good: #6fd08f; --good-bg: #1b3324; --good-lane: #19281e; --bad: #ff8a80; --bad-bg: #3a1d1a;
      --rank: #93b4ff; --rank-bg: #1d2a47; --chip-bg: #2b2b28;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text);
         font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  .top {{ position: sticky; top: 0; z-index: 2; background: var(--bg); border-bottom: 1px solid var(--border);
          padding: 14px 24px; display: flex; flex-wrap: wrap; gap: 8px 24px; align-items: baseline; }}
  h1 {{ font-size: 18px; margin: 0; }}
  .stats {{ color: var(--muted); }}
  .stats b {{ color: var(--text); font-variant-numeric: tabular-nums; }}
  .stats .good b {{ color: var(--good); }}
  .filters {{ margin-left: auto; display: flex; gap: 16px; color: var(--muted); }}
  .filters label {{ cursor: pointer; }}
  main {{ padding: 16px 24px 40px; display: flex; flex-direction: column; gap: 20px; }}
  .meta {{ color: var(--muted); }}

  .event {{ background: var(--event-bg); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px 16px; }}
  .event-head {{ display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; margin-bottom: 12px; }}
  h2 {{ font-size: 16px; margin: 0; }}
  .bursts {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-start; }}

  .burst {{ background: var(--burst-bg); border: 1px solid var(--border); border-radius: 10px; padding: 10px; max-width: 100%; }}
  .burst header {{ display: flex; flex-wrap: wrap; gap: 2px 8px; align-items: baseline; margin-bottom: 8px; }}
  h3 {{ font-size: 13px; margin: 0; }}
  .burst .meta {{ font-size: 12px; }}
  .lanes {{ display: flex; gap: 10px; align-items: stretch; overflow-x: auto; }}
  .lane {{ border-radius: 8px; padding: 6px; border: 2px solid transparent; }}
  .lane-label {{ font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
                 color: var(--muted); margin: 0 2px 6px; }}
  .lane-label span {{ font-weight: 400; }}
  .lane.keep {{ background: var(--good-lane); border-color: var(--good); }}
  .lane.keep .lane-label {{ color: var(--good); }}
  .cards {{ display: flex; gap: 8px; }}

  .card {{ margin: 0; flex: 0 0 auto; width: 150px; background: var(--surface);
           border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
  .card img, .missing {{ display: block; width: 100%; height: 110px; object-fit: contain; background: var(--chip-bg); }}
  .card.candidate {{ width: 220px; border-color: var(--good); }}
  .card.candidate img, .card.candidate .missing {{ height: 170px; }}
  .card.unranked img {{ opacity: .55; }}
  .missing {{ display: grid; place-items: center; color: var(--muted); }}
  figcaption {{ padding: 6px 8px 8px; }}
  .badges {{ display: flex; flex-wrap: wrap; gap: 4px; min-height: 22px; }}
  .badge {{ font-size: 12px; padding: 1px 7px; border-radius: 999px; background: var(--chip-bg);
            font-variant-numeric: tabular-nums; }}
  .badge.rank {{ background: var(--rank-bg); color: var(--rank); font-weight: 600; }}
  .badge.good {{ background: var(--good); color: var(--surface); font-weight: 600; }}
  .badge.bad {{ background: var(--bad-bg); color: var(--bad); }}
  .badge.muted {{ color: var(--muted); }}
  .name {{ margin-top: 4px; color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

  body.only-candidates .lane:not(.keep),
  body.only-candidates .burst:not(.has-candidate),
  body.only-candidates .event:not(.has-candidate) {{ display: none; }}
  body.hide-unranked .lane.unranked,
  body.hide-unranked .burst:not(:has(.lane.keep, .lane.rest)),
  body.hide-unranked .event:not(:has(.lane.keep, .lane.rest)) {{ display: none; }}
  footer {{ color: var(--muted); font-size: 12px; padding: 0 24px 24px; }}
  @media (max-width: 600px) {{
    .top, main, footer {{ padding-left: 16px; padding-right: 16px; }}
    .filters {{ margin-left: 0; }}
    .event {{ padding: 12px; }}
    .card {{ width: 120px; }}
    .card img, .missing {{ height: 90px; }}
    .card.candidate {{ width: 170px; }}
    .card.candidate img, .card.candidate .missing {{ height: 130px; }}
  }}
</style>
</head>
<body>
  <div class="top">
    <h1>Cully Report</h1>
    <div class="stats"><b>{len(photos)}</b> photos · <b>{n_events}</b> events · <b>{n_bursts}</b> bursts ·
      <span class="good"><b>{candidates}</b> candidates</span> · <b>{closed}</b> eyes closed · <b>{len(photos) - len(ranked)}</b> unranked</div>
    <div class="filters">
      <label><input type="checkbox" data-class="only-candidates"> Candidates only</label>
      <label><input type="checkbox" data-class="hide-unranked"> Hide unranked</label>
    </div>
  </div>
  <main>{''.join(sections)}
  </main>
  <footer>Generated {generated} from {html.escape(catalog_path)}. Click a photo to open the full image.</footer>
<script>
  document.querySelectorAll(".filters input").forEach(box =>
    box.addEventListener("change", () => document.body.classList.toggle(box.dataset.class, box.checked)));
</script>
</body>
</html>
"""


def open_in_browser(url: str):
    """Opens url in a known browser, falling back to the system default.
    The default .html handler isn't always a browser (it can be any app)."""
    for name in ("firefox", "google-chrome", "chromium", "chrome"):
        try:
            webbrowser.get(name).open(url)
            return
        except webbrowser.Error:
            continue
    webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(description="Write an HTML report of the pipeline results.")
    parser.add_argument("--catalog", type=Path, help="catalog file to read (default: the real catalog)")
    parser.add_argument("--out", type=Path, help="report folder (default: <output_path>/report from config.json)")
    parser.add_argument("--open", action="store_true", help="open the report in the browser when done")
    args = parser.parse_args()

    settings = Settings()
    out = args.out or Path(Config().output_path) / "report"
    thumbs = out / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)

    catalog = Catalog(str(args.catalog)) if args.catalog else Catalog()
    photos = catalog.get_report_photos(settings.face_threshold)
    catalog_path = catalog.catalog_path
    catalog.close()

    thumbs_ok = set()
    unreadable = []
    for photo in photos:
        if make_thumbnail(Path(photo.image_path), thumbs / f"{photo.image_hash}.jpg"):
            thumbs_ok.add(photo.image_hash)
        else:
            unreadable.append(photo.image_path)
    if unreadable:
        print(f"[report.py] Could not read {len(unreadable)} photos, e.g. {unreadable[0]}")
        if any(not Path(p).is_absolute() for p in unreadable):
            print("[report.py] Some paths are relative; rescan their folder to store absolute paths:"
                  " python main.py <folder> --steps scan")

    index = out / "index.html"
    index.write_text(build_html(photos, thumbs_ok, catalog_path), encoding="utf-8")
    print(f"[report.py] Report written to {index}")
    if args.open:
        open_in_browser(index.resolve().as_uri())


if __name__ == "__main__":
    main()
