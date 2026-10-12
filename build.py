#!/usr/bin/env python3
"""
Build the static site from data/reactors.yml into _site/.

    python3 scripts/build.py

Produces:
    _site/index.html            the record, map and lifecycle ladder
    _site/reactors/<id>.html    one page per project
    _site/changes.html          change log generated from git history
    _site/data/reactors.csv     flat export
    _site/data/reactors.json    full export

Nothing here talks to the network and nothing is cached: the YAML file is the
only input, so the site cannot drift from the data.
"""

import csv
import json
import os
import shutil
import subprocess
from datetime import date, datetime

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

DATA_FILE = "data/reactors.yml"
OUT = "_site"

# Must match ALLOWED_STATUS in scripts/validate_data.py.
STAGE_COLOURS = {
    "Announced": "#96A09A",
    "Approved": "#5B7D93",
    "Under Construction": "#B5830F",
    "Commissioning": "#2E7FA8",
    "Operational": "#1A7A55",
    "On Hold": "#7E6A42",
    "Cancelled": "#9E3B3B",
}
STAGE_ORDER = list(STAGE_COLOURS)

# The ladder reads left to right as a lifecycle; the table reads top down as
# "what is real".
DISPLAY_ORDER = ["Operational", "Commissioning", "Under Construction",
                 "Approved", "Announced", "On Hold", "Cancelled"]

CHRONOLOGY_LABELS = [
    ("announced", "Announced"),
    ("approved", "Approved"),
    ("construction_start", "First concrete"),
    ("first_criticality", "First criticality"),
    ("grid_connection", "Grid connection"),
    ("commercial_operation", "Commercial operation"),
    ("expected_commercial_operation", "Expected operation"),
]


def iso(value):
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)


def short_developer(name):
    """Table column needs something that fits. Keep the acronym if there is one."""
    if not name:
        return ""
    for acronym in ("CNNC", "CGN", "SPIC", "Huaneng", "CNEC"):
        if acronym.lower() in name.lower():
            return acronym
    return name.split(" with ")[0][:28]


def git_log():
    """Change log straight from the commit history of the data file."""
    try:
        out = subprocess.run(
            ["git", "log", "--date=short", "--format=%ad\t%s", "--", DATA_FILE],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    commits = []
    for line in out.strip().splitlines():
        if "\t" in line:
            d, subject = line.split("\t", 1)
            commits.append({"date": d, "subject": subject})
    return commits


def prepare(raw):
    """Flatten one YAML entry into the shape the templates expect."""
    site = raw.get("site") or {}
    out = raw.get("output") or {}
    dates = raw.get("dates") or {}
    narrative = raw.get("narrative") or {}
    ver = raw.get("verification") or {}
    milestones = sorted(
        ({"date": iso(m.get("date")), "event": m.get("event")}
         for m in raw.get("milestones") or []),
        key=lambda m: m["date"] or "",
    )
    sources = [
        {"url": s.get("url"), "title": s.get("title"), "date": iso(s.get("date"))}
        for s in raw.get("sources") or []
    ]
    last = milestones[-1]["date"] if milestones else None
    status = raw.get("status")

    # A project with no fixed site is drawn hollow on the map rather than
    # dropped, because "approved but unsited" is a real and interesting state.
    sited = "not fixed" not in (site.get("name") or "").lower()

    searchable = " ".join(filter(None, [
        raw.get("name_en"), raw.get("name_zh"), raw.get("design"),
        raw.get("design_family"), raw.get("developer_en"), site.get("province"),
        site.get("name"), status,
    ])).lower()

    return {
        "id": raw.get("id"),
        "name_en": raw.get("name_en"),
        "name_zh": raw.get("name_zh") or "",
        "design": raw.get("design"),
        "design_family": raw.get("design_family"),
        "developer_en": raw.get("developer_en"),
        "developer_short": short_developer(raw.get("developer_en")),
        "operator": raw.get("operator"),
        "site_name": site.get("name"),
        "province": site.get("province"),
        "lat": site.get("lat"),
        "lon": site.get("lon"),
        "sited": sited,
        "deployment": raw.get("deployment"),
        "purpose": raw.get("purpose"),
        "status": status,
        "colour": STAGE_COLOURS.get(status, "#96A09A"),
        "thermal_mwt": out.get("thermal_mwt"),
        "module_mwe": out.get("module_mwe"),
        "modules": out.get("modules"),
        "plant_mwe": out.get("plant_mwe"),
        "basis": out.get("basis"),
        "chronology": [(label, iso(dates.get(key))) for key, label in CHRONOLOGY_LABELS],
        "what_it_is": narrative.get("what_it_is"),
        "why_it_matters": narrative.get("why_it_matters"),
        "milestones": milestones,
        "last_milestone_date": last,
        "last_milestone_sort": (last or "0000-00-00").replace("-", ""),
        "sources": sources,
        "sources_count": len(sources),
        "verified": bool(ver.get("verified")),
        "verification_note": ver.get("note"),
        "search": searchable,
    }


def main():
    with open(DATA_FILE, encoding="utf-8") as fh:
        reactors = [prepare(r) for r in (yaml.safe_load(fh).get("reactors") or [])]

    # Order the table the way a reader cares: built things first, dead things
    # last, biggest first inside each stage.
    reactors.sort(key=lambda r: (DISPLAY_ORDER.index(r["status"])
                                 if r["status"] in DISPLAY_ORDER else 99,
                                 -(r["plant_mwe"] or 0)))

    ladder = []
    for stage in STAGE_ORDER:
        group = [r for r in reactors if r["status"] == stage]
        if group:
            ladder.append({
                "name": stage,
                "colour": STAGE_COLOURS[stage],
                "count": len(group),
                "mwe": sum(r["plant_mwe"] or 0 for r in group),
            })

    totals = {
        "count": len(reactors),
        # Cancelled and stalled capacity is deliberately excluded. Announced
        # megawatts that were never built are not generation.
        "operational_mwe": sum(r["plant_mwe"] or 0
                               for r in reactors if r["status"] == "Operational"),
    }

    env = Environment(loader=FileSystemLoader("templates"),
                      autoescape=select_autoescape(["html"]))

    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(f"{OUT}/reactors", exist_ok=True)
    os.makedirs(f"{OUT}/data", exist_ok=True)
    shutil.copy("static/style.css", f"{OUT}/style.css")
    open(f"{OUT}/.nojekyll", "w").close()

    common = {"built": date.today().isoformat(), "count": len(reactors)}

    map_points = [
        {k: r[k] for k in ("id", "name_en", "lat", "lon", "status",
                           "plant_mwe", "colour", "sited")}
        for r in reactors if r["lat"] is not None
    ]

    with open(f"{OUT}/index.html", "w", encoding="utf-8") as fh:
        fh.write(env.get_template("index.html").render(
            page="index", root="", reactors=reactors, ladder=ladder,
            totals=totals, geojson=json.dumps(map_points), **common))

    tpl = env.get_template("reactor.html")
    for r in reactors:
        with open(f"{OUT}/reactors/{r['id']}.html", "w", encoding="utf-8") as fh:
            fh.write(tpl.render(page="reactor", root="../", r=r, **common))

    with open(f"{OUT}/changes.html", "w", encoding="utf-8") as fh:
        fh.write(env.get_template("changes.html").render(
            page="changes", root="", commits=git_log(), **common))

    # Exports. Anyone should be able to check the numbers without cloning.
    with open(f"{OUT}/data/reactors.json", "w", encoding="utf-8") as fh:
        json.dump(reactors, fh, ensure_ascii=False, indent=2)

    columns = ["id", "name_en", "name_zh", "design", "design_family",
               "developer_en", "province", "site_name", "deployment", "purpose",
               "status", "thermal_mwt", "module_mwe", "modules", "plant_mwe",
               "last_milestone_date", "verified", "sources_count"]
    with open(f"{OUT}/data/reactors.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(reactors)

    print(f"Built {len(reactors)} entries into {OUT}/ "
          f"({totals['operational_mwe']} MWe operational)")


if __name__ == "__main__":
    main()
