#!/usr/bin/env python3
"""
Validate data/reactors.yml before the site is built.

This file is the gatekeeper. It catches the mistakes that otherwise fail
silently: a mistyped status that drops an entry out of every count, a
malformed date, swapped coordinates that put a reactor in the sea, an entry
with no source, a project that quietly grew past the SMR scope boundary, or
a chronology that runs backwards.

Run from the repo root:
    python3 scripts/validate_data.py

Exit code 0 means clean (warnings may still print), 1 means errors.
The deploy workflow runs this first and stops if it fails.
"""

import sys
from datetime import date, timedelta

import yaml

DATA_FILE = "data/reactors.yml"

# ---------------------------------------------------------------------------
# Controlled vocabularies. These must match the comment block at the top of
# reactors.yml and the colour map in scripts/build.py. Three places, one truth:
# if you add a status, add it in all three or the build will tell you.
# ---------------------------------------------------------------------------
ALLOWED_STATUS = {
    "Announced", "Approved", "Under Construction",
    "Commissioning", "Operational", "On Hold", "Cancelled",
}
ALLOWED_DESIGN_FAMILY = {"Integral PWR", "Compact PWR", "HTGR", "Molten Salt", "Other"}
ALLOWED_DEPLOYMENT = {"Land-based", "Floating", "Barge-mounted"}
ALLOWED_PURPOSE = {"Electricity", "Cogeneration"}
ALLOWED_DEVELOPER_TYPE = {"State-Owned", "Academic-Industrial", "JV", "Private"}

# IAEA定义: an SMR is up to 300 MWe per module. Plant totals may exceed this
# where several modules share a site, so the ceiling is checked per module.
SMR_MODULE_CEILING_MWE = 300

# Generous bounding box for mainland China plus its claimed maritime areas.
LAT_RANGE = (3.0, 54.0)
LON_RANGE = (73.0, 136.0)

# Chronology, in the order events must occur.
DATE_ORDER = [
    "announced", "approved", "construction_start",
    "first_criticality", "grid_connection", "commercial_operation",
]

# Sources that identify an organisation but do not evidence a specific claim.
# An entry may cite these while it is still a seed, but not once it claims to
# be verified.
LANDING_PAGES = {
    "pris.iaea.org", "aris.iaea.org", "en.cnnc.com.cn", "www.cgnpc.com.cn",
    "www.spic.com.cn", "www.chng.com.cn", "www.inet.tsinghua.edu.cn",
}

# Aggregators and proxies that hide the real publisher.
BANNED_HOSTS = {"news.google.com", "t.co", "bit.ly", "baijiahao.baidu.com"}

STALE_AFTER_DAYS = 180

errors: list[str] = []
warnings: list[str] = []


def err(label, msg):
    errors.append(f"{label}: {msg}")


def warn(label, msg):
    warnings.append(f"{label}: {msg}")


def host_of(url: str) -> str:
    return url.split("//", 1)[-1].split("/", 1)[0].lower()


def as_date(value):
    """Return a date, or None if absent, or False if unparseable."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return False


def check_date(label, field, value, required=False):
    parsed = as_date(value)
    if parsed is None and required:
        err(label, f"{field} is missing")
    if parsed is False:
        err(label, f"{field} '{value}' is not a YYYY-MM-DD date")
    return parsed


def check_enum(label, field, value, allowed):
    if value not in allowed:
        err(label, f"{field} '{value}' is not one of: {', '.join(sorted(allowed))}")


def check_site(label, site):
    if not site:
        err(label, "site block is missing")
        return
    lat, lon = site.get("lat"), site.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        err(label, f"lat/lon missing or not numeric ({lat}, {lon})")
        return
    if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
        err(label, f"coordinates ({lat}, {lon}) fall outside China — swapped lat/lon?")
    if not site.get("province"):
        err(label, "site.province is missing")


def check_output(label, out):
    if not out:
        err(label, "output block is missing")
        return
    module = out.get("module_mwe")
    modules = out.get("modules")
    plant = out.get("plant_mwe")
    if not isinstance(module, (int, float)):
        err(label, "output.module_mwe missing or not numeric")
        return
    if module > SMR_MODULE_CEILING_MWE:
        err(label, f"module_mwe {module} exceeds the {SMR_MODULE_CEILING_MWE} MWe "
                   "SMR ceiling — either the figure is wrong or this entry is out of scope")
    if isinstance(modules, int) and isinstance(plant, (int, float)):
        expected = module * modules
        # Allow 10% for turbine-hall losses and rounding in published figures.
        if abs(expected - plant) > max(5, 0.1 * expected):
            warn(label, f"plant_mwe {plant} is not close to module_mwe x modules ({expected})")
    if out.get("basis") not in {"design", "nameplate", "reported"}:
        err(label, f"output.basis '{out.get('basis')}' must be design, nameplate or reported")


def check_chronology(label, dates, status):
    if not dates:
        err(label, "dates block is missing")
        return
    seen = []
    for field in DATE_ORDER:
        d = check_date(label, f"dates.{field}", dates.get(field))
        if isinstance(d, date):
            seen.append((field, d))
    for (f1, d1), (f2, d2) in zip(seen, seen[1:]):
        if d2 < d1:
            err(label, f"dates.{f2} ({d2}) is before dates.{f1} ({d1})")
    check_date(label, "dates.expected_commercial_operation",
               dates.get("expected_commercial_operation"))

    # Status has to agree with the dates. This is the check that catches a
    # tracker going stale: a reactor that reached the grid but still reads
    # Under Construction.
    if status == "Operational" and not dates.get("commercial_operation"):
        err(label, "status is Operational but dates.commercial_operation is empty")
    if status in {"Announced", "Approved"} and dates.get("construction_start"):
        err(label, f"status is {status} but a construction_start date is recorded")
    if dates.get("grid_connection") and status in {"Under Construction", "Approved", "Announced"}:
        err(label, f"status is {status} but the unit has a grid_connection date")


def check_sources(label, sources, verified):
    if not sources:
        err(label, "no sources — every entry needs at least one")
        return
    for i, s in enumerate(sources):
        url = str(s.get("url") or "")
        tag = f"sources[{i}]"
        if not url.startswith(("http://", "https://")):
            err(label, f"{tag} url '{url}' is not an http(s) URL")
            continue
        host = host_of(url)
        if host in BANNED_HOSTS:
            err(label, f"{tag} is an aggregator or shortener ({host}) — cite the publisher")
        if verified and host in LANDING_PAGES:
            err(label, f"{tag} is a landing page ({host}) and cannot support a "
                       "verified entry — cite the specific filing, notice or dated article")
        if not s.get("title"):
            err(label, f"{tag} has no title")
        check_date(label, f"{tag}.date", s.get("date"), required=True)


def check_verification(label, block):
    if not block:
        err(label, "verification block is missing")
        return False
    verified = block.get("verified")
    if not isinstance(verified, bool):
        err(label, "verification.verified must be true or false")
        return False
    last = check_date(label, "verification.last_verified", block.get("last_verified"))
    if verified and not isinstance(last, date):
        err(label, "verification.verified is true but last_verified is empty")
    if isinstance(last, date):
        if last > date.today():
            err(label, f"verification.last_verified {last} is in the future")
        elif date.today() - last > timedelta(days=STALE_AFTER_DAYS):
            warn(label, f"not re-checked since {last} — over {STALE_AFTER_DAYS} days")
    if not verified:
        warn(label, "unverified seed entry — check it against a primary source, "
                    "replace the landing-page sources, then set verified: true")
    return verified


def main():
    with open(DATA_FILE, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    reactors = data.get("reactors") or []
    if not reactors:
        print(f"{DATA_FILE} contains no reactors.", file=sys.stderr)
        return 1

    ids = set()
    for r in reactors:
        rid = r.get("id", "<no id>")
        label = rid
        if not rid or rid == "<no id>":
            err("<entry>", "missing id")
        if rid in ids:
            err(label, "duplicate id")
        ids.add(rid)
        if not r.get("name_en"):
            err(label, "name_en is missing")

        status = r.get("status")
        check_enum(label, "status", status, ALLOWED_STATUS)
        check_enum(label, "design_family", r.get("design_family"), ALLOWED_DESIGN_FAMILY)
        check_enum(label, "deployment", r.get("deployment"), ALLOWED_DEPLOYMENT)
        check_enum(label, "purpose", r.get("purpose"), ALLOWED_PURPOSE)
        check_enum(label, "developer_type", r.get("developer_type"), ALLOWED_DEVELOPER_TYPE)

        check_site(label, r.get("site"))
        check_output(label, r.get("output"))
        check_chronology(label, r.get("dates"), status)

        narrative = r.get("narrative") or {}
        for field in ("what_it_is", "why_it_matters"):
            if not narrative.get(field):
                warn(label, f"narrative.{field} is empty")

        for i, m in enumerate(r.get("milestones") or []):
            check_date(label, f"milestones[{i}].date", m.get("date"), required=True)
            if not m.get("event"):
                err(label, f"milestones[{i}] has no event text")

        verified = check_verification(label, r.get("verification"))
        check_sources(label, r.get("sources"), verified)

    for w in warnings:
        print(f"WARNING  {w}")
    for e in errors:
        print(f"ERROR    {e}", file=sys.stderr)

    print(f"\n{len(reactors)} entries checked. "
          f"{len(errors)} errors, {len(warnings)} warnings.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
