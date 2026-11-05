"""Business deep dive: public Google Maps listing + review analysis for one venue.

Business-level information only. Nothing here looks up owners, employees or
reviewers; reviewer names are dropped as soon as reviews are fetched.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone

# Review language grouped by theme. Drawn from published indicators for
# trafficking-linked venues (e.g. Polaris Project's illicit massage business
# research). Every one of these also turns up in ordinary reviews, so a hit
# is a reason to read the review, not a finding.
INDICATOR_THEMES: dict[str, list[str]] = {
    "Access & security": [
        "buzzer", "buzzed in", "locked door", "door was locked", "doors locked",
        "back door", "ring the bell", "rang the bell", "cameras everywhere",
    ],
    "Cash & payment": [
        "cash only", "only cash", "only takes cash", "only accept cash",
        "cash tip", "no receipt", "card machine", "card reader was broken",
    ],
    "Late hours": [
        "after hours", "open late", "late night", "midnight", "24 hours", "2am", "3am",
    ],
    "Worker welfare": [
        "scared", "afraid", "lives there", "live there", "sleep there",
        "sleeping there", "living there", "no english", "doesn't speak english",
        "don't speak english", "didn't speak english", "couldn't speak english",
        "can't speak english", "new girl", "new girls",
        "very young", "looked young",
    ],
    "Sexual-services language": [
        "happy ending", "full service", "extra service", "more than a massage",
        "not a real massage", "inappropriate", "touched me", "sexual",
    ],
    "Lodging activity": [
        "by the hour", "hourly rate", "pay by the hour", "in and out all night",
        "men coming and going", "lots of traffic", "prostitution", "police",
    ],
}

_THEME_PATTERNS = {
    theme: re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")\b", re.I)
    for theme, words in INDICATOR_THEMES.items()
}

REVIEW_DEPTHS = {  # label -> number of review pages (page 1 has 8, later pages 20)
    "~10 most recent reviews (2 searches)": 1,
    "~30 most recent reviews (3 searches)": 2,
    "~50 most recent reviews (4 searches)": 3,
}

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
LATE_CLOSE_MIN = 23 * 60  # closing at or after 11 PM counts as late


# ------------------------------------------------------------------
# Geometry
# ------------------------------------------------------------------
def haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres (works on scalars or numpy/pandas arrays)."""
    import numpy as np

    r = 6_371_000
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lng2) - np.radians(lng1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


# ------------------------------------------------------------------
# Opening hours
# ------------------------------------------------------------------
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?", re.I)


def _to_minutes(token: str, default_ampm: str | None) -> tuple[int, str | None] | None:
    m = _TIME_RE.search(token)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    ampm = (m.group(3) or default_ampm or "").upper() or None
    if ampm == "PM" and hour != 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0
    return hour * 60 + minute, ampm


def closing_minutes(day_hours: str) -> int | None:
    """Minutes after midnight the venue closes, using 24*60+ for past-midnight.

    Returns 48*60 for 'Open 24 hours', -1 for 'Closed', None if unparseable.
    """
    if not day_hours:
        return None
    s = (day_hours.replace(" ", " ").replace(" ", " ")
         .replace("–", "-").replace("—", "-").replace("–", "-").strip())
    low = s.lower()
    if "24 hours" in low:
        return 48 * 60
    if low.startswith("closed"):
        return -1
    last_range = s.split(",")[-1]
    if "-" not in last_range:
        return None
    start_tok, end_tok = last_range.rsplit("-", 1)
    end = _to_minutes(end_tok, None)
    if end is None:
        return None
    start = _to_minutes(start_tok, end[1])
    end_min = end[0]
    # A range that ends earlier than it starts runs past midnight (e.g. 6 PM-2 AM).
    if start is not None and end_min <= start[0]:
        end_min += 24 * 60
    return end_min


def summarize_hours(operating_hours: dict | None) -> dict:
    """Per-day hours plus late-night / 24-hour flags."""
    if not operating_hours:
        return {"days": {}, "late_days": [], "open_24h": False, "known": False}
    days = {d: operating_hours.get(d, "") for d in DAYS if d in operating_hours} or dict(operating_hours)
    late, any_24 = [], False
    for d, h in days.items():
        c = closing_minutes(h)
        if c is None or c < 0:
            continue
        if c >= 48 * 60:
            any_24 = True
            late.append(d)
        elif c >= LATE_CLOSE_MIN:
            late.append(d)
    return {"days": days, "late_days": late, "open_24h": any_24, "known": True}


# ------------------------------------------------------------------
# Reviews
# ------------------------------------------------------------------
def _norm(text: str) -> str:
    return (text or "").replace("\u2019", "'").replace("\u2018", "'")


def scan_review(text: str) -> dict[str, list[str]]:
    """Theme -> distinct indicator phrases found in one review."""
    found = {}
    text = _norm(text)
    for theme, pat in _THEME_PATTERNS.items():
        hits = sorted({m.lower() for m in pat.findall(text)})
        if hits:
            found[theme] = hits
    return found


def highlight(text: str, phrases: list[str]) -> str:
    import html

    out = html.escape(_norm(text), quote=False)
    for p in sorted(set(phrases), key=len, reverse=True):
        out = re.sub(rf"\b({re.escape(html.escape(p, quote=False))})\b", r"<mark>\1</mark>", out, flags=re.I)
    return out


def _parse_date(r: dict):
    iso = r.get("iso_date") or r.get("iso_date_of_last_edit")
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def analyze_reviews(reviews: list[dict]) -> dict:
    """Rating mix, timeline and indicator hits for a list of SerpAPI reviews."""
    ratings = Counter()
    months = Counter()
    hits, theme_counts = [], Counter()
    with_text = 0
    for r in reviews:
        rating = r.get("rating")
        if isinstance(rating, (int, float)):
            ratings[int(round(rating))] += 1
        d = _parse_date(r)
        if d:
            months[d.strftime("%Y-%m")] += 1
        text = r.get("snippet") or (r.get("extracted_snippet") or {}).get("original") or ""
        if text:
            with_text += 1
        found = scan_review(text)
        if found:
            for theme in found:
                theme_counts[theme] += 1
            hits.append({
                "themes": found,
                "text": text,
                "rating": rating,
                "date": r.get("date", ""),
                "iso": d.isoformat() if d else "",
            })
    total = sum(ratings.values())
    dates = [_parse_date(r) for r in reviews]
    dates = [d for d in dates if d]
    return {
        "count": len(reviews),
        "with_text": with_text,
        "ratings": {s: ratings.get(s, 0) for s in range(1, 6)},
        "one_star_share": (ratings.get(1, 0) / total) if total else None,
        "months": dict(sorted(months.items())),
        "oldest": min(dates).date().isoformat() if dates else None,
        "newest": max(dates).date().isoformat() if dates else None,
        "hits": hits,
        "theme_counts": {t: theme_counts.get(t, 0) for t in INDICATOR_THEMES},
    }


# ------------------------------------------------------------------
# SerpAPI fetch
# ------------------------------------------------------------------
def _pick_listing(res: dict, lat: float, lng: float) -> tuple[dict | None, float | None]:
    """The search result nearest the venue's mapped location."""
    if res.get("place_results"):
        cands = [res["place_results"]]
    else:
        cands = res.get("local_results") or []
    best, best_d = None, None
    for c in cands:
        g = c.get("gps_coordinates") or {}
        d = (float(haversine_m(lat, lng, g["latitude"], g["longitude"]))
             if "latitude" in g and "longitude" in g else None)
        if best is None or (d is not None and (best_d is None or d < best_d)):
            best, best_d = c, d
    return best, best_d


def fetch_business(name: str, lat: float, lng: float, pages: int, api_key: str, search_cls=None) -> dict:
    """Look up the venue on Google Maps via SerpAPI and pull its newest reviews."""
    if search_cls is None:
        from serpapi import GoogleSearch as search_cls

    res = search_cls({"engine": "google_maps", "type": "search", "q": name,
                      "ll": f"@{lat},{lng},17z", "api_key": api_key}).get_dict()
    if "error" in res and not res.get("place_results") and not res.get("local_results"):
        return {"error": res["error"]}

    place, dist = _pick_listing(res, lat, lng)
    if not place or not place.get("data_id"):
        return {"error": "No matching Google Maps listing found."}

    reviews, token, searches = [], None, 1
    for page in range(pages):
        params = {"engine": "google_maps_reviews", "data_id": place["data_id"],
                  "sort_by": "newestFirst", "hl": "en", "api_key": api_key}
        if token:
            params.update({"next_page_token": token, "num": 20})
        rr = search_cls(params).get_dict()
        searches += 1
        batch = rr.get("reviews") or []
        # Keep only what the analysis uses; drop reviewer identities.
        reviews.extend({k: r.get(k) for k in ("rating", "date", "iso_date", "snippet")} for r in batch)
        token = (rr.get("serpapi_pagination") or {}).get("next_page_token")
        if not token or not batch:
            break

    listing = {
        "title": place.get("title", ""),
        "address": place.get("address", ""),
        "category": place.get("type") or ", ".join(place.get("types") or []),
        "phone": place.get("phone", ""),
        "website": place.get("website", ""),
        "rating": place.get("rating"),
        "review_total": place.get("reviews"),
        "price": place.get("price", ""),
        "open_state": place.get("open_state", ""),
        "distance_m": dist,
    }
    return {
        "listing": listing,
        "hours": summarize_hours(place.get("operating_hours")),
        "reviews": analyze_reviews(reviews),
        "searches_used": searches,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


# ------------------------------------------------------------------
# Signals + report
# ------------------------------------------------------------------
def signals(result: dict) -> list[tuple[str, bool | None, str]]:
    """(signal, present?, detail). None = couldn't tell."""
    out = []
    hrs = result["hours"]
    if hrs["known"]:
        late = hrs["late_days"]
        detail = ("open 24 hours" if hrs["open_24h"] else
                  f"open until 11 PM or later on {len(late)} day(s)" if late else "closes before 11 PM")
        out.append(("Late-night or 24-hour hours", bool(late), detail))
    else:
        out.append(("Late-night or 24-hour hours", None, "no hours listed"))

    rv = result["reviews"]
    tc = rv["theme_counts"]
    for theme in INDICATOR_THEMES:
        n = tc.get(theme, 0)
        out.append((f"Review language: {theme.lower()}", n > 0 if rv["count"] else None,
                    f"{n} of {rv['count']} reviews" if rv["count"] else "no reviews read"))

    share = rv["one_star_share"]
    out.append(("High share of 1-star reviews (25%+)", None if share is None else share >= 0.25,
                "n/a" if share is None else f"{share:.0%} of rated reviews"))
    lst = result["listing"]
    out.append(("No website on listing", not bool(lst["website"]), lst["website"] or "none listed"))
    return out


def report_markdown(row: dict, result: dict | None, nearby: list[dict], disclaimer: str) -> str:
    lines = [f"# Business profile: {row['name']}", "", f"> {disclaimer.replace('**', '')}", ""]
    lines += [
        "## Profile score",
        f"- Score: **{row['score']} / 10** ({row['tier']})",
        f"- Venue type: {row['type'].replace('_', ' ')} ({row['venue_pts']:g} pts)",
        f"- Area vulnerability: {row['area_pts']:g} pts · Statewide trend: {row['trend_pts']:g} pts",
        f"- Address (OpenStreetMap): {row.get('address') or 'n/a'} · {row.get('county_name') or ''}",
        "",
        "## Nearby profile matches (within 1 km)",
    ]
    if nearby:
        lines += [f"- {n['name']} ({n['type']}, {n['distance_m']:.0f} m, score {n['score']})" for n in nearby]
    else:
        lines.append("- None")
    if result and "error" not in result:
        L, H, R = result["listing"], result["hours"], result["reviews"]
        lines += [
            "", "## Google Maps listing",
            f"- Matched: {L['title']}, {L['address']}"
            + (f" ({L['distance_m']:.0f} m from mapped location)" if L["distance_m"] is not None else ""),
            f"- Category: {L['category'] or 'n/a'} · Rating: {L['rating'] or 'n/a'} ({L['review_total'] or 0} reviews)",
            f"- Website: {L['website'] or 'none'} · Phone: {L['phone'] or 'none'} · Status: {L['open_state'] or 'n/a'}",
        ]
        if H["known"]:
            lines += ["", "### Hours"] + [f"- {d.title()}: {h}" for d, h in H["days"].items()]
        lines += ["", "## Signals"]
        for name, present, detail in signals(result):
            mark = "yes" if present else ("unknown" if present is None else "no")
            lines.append(f"- {name}: **{mark}** ({detail})")
        lines += ["", f"## Reviews with indicator language ({len(R['hits'])} of {R['count']} read)"]
        for h in R["hits"]:
            phrases = "; ".join(f"{t}: {', '.join(p)}" for t, p in h["themes"].items())
            lines += [f"- {h['date']} · {h['rating']}★ · {phrases}", f"  > {h['text']}"]
        lines += ["", f"_Fetched {result['fetched_at']} via SerpAPI ({result['searches_used']} searches)._"]
    return "\n".join(lines) + "\n"
