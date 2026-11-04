import html
import json
import re
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="NOVA Risk Profile Explorer", page_icon="🛡️", layout="wide")

DATA_DIR = Path(__file__).parent
RAW_BASE = "https://raw.githubusercontent.com/Hazemadam/osint-dashboard/main/"

DISCLAIMER = (
    "**Profile match, not evidence.** Scores show how closely a location fits patterns "
    "in FBI trafficking data (venue type, area conditions, statewide trends). Most "
    "businesses that fit this profile are entirely legitimate. Use this to prioritize "
    "further research, never as grounds on its own for accusations, reports or action "
    "against a business."
)

# Venue categories the data pipeline collects (anything else is legacy noise,
# e.g. the parking spaces an old query picked up by accident).
KNOWN_TYPES = {
    "hotel", "motel", "guest_house", "spa", "massage",
    "bar", "nightclub", "cafe", "restaurant",
    "apartments", "residential", "house",
}

# Venue weights (max 6) follow the FBI location breakdown: lodging and
# massage/spa venues first, residences second, everything else low.
VENUE_WEIGHTS = [
    (r"motel|hotel|guest_house|spa|massage", 6.0),
    (r"apartment|residential|home|house|studio", 4.0),
]
DEFAULT_VENUE_WEIGHT = 1.0
AREA_MAX = 3.0
TREND_MAX = 1.0

TIERS = [  # (min score, label, map colour, icon)
    (8.0, "Strong match", "#e5484d", "🔴"),
    (5.0, "Moderate match", "#f5a524", "🟠"),
    (0.0, "Weak match", "#3e8ed0", "🔵"),
]

REVIEW_FLAGS = ["buzzer", "locked", "cash only", "scared", "after hours", "back door"]


# ==========================================
# 1. DATA
# ==========================================
def _read(name: str, reader):
    """Read a data file from the repo checkout, falling back to GitHub."""
    local = DATA_DIR / name
    try:
        return reader(local if local.exists() else RAW_BASE + name)
    except Exception as e:  # missing/unreadable file shouldn't take the app down
        st.sidebar.warning(f"Couldn't load {name}: {e}")
        return pd.DataFrame()


def _fbi_series(df: pd.DataFrame) -> pd.Series:
    """First row of an FBI CDE export as a monthly series (drops trailing blanks)."""
    if df.empty:
        return pd.Series(dtype=float)
    s = pd.to_numeric(df.iloc[0, 1:], errors="coerce").dropna()
    s.index = pd.to_datetime(s.index, format="%m-%Y", errors="coerce")
    return s[s.index.notna()]


@st.cache_data(ttl=3600, show_spinner="Loading data…")
def load_data():
    poi = _read("nova_data.parquet", pd.read_parquet)
    census = _read("vulnerability_data.parquet", pd.read_parquet)
    fbi = {
        "servitude": _read("fbi_servitude.csv", lambda p: pd.read_csv(p, encoding="utf-8-sig")),
        "sex_acts": _read("fbi_sex_acts.csv", lambda p: pd.read_csv(p, encoding="utf-8-sig")),
        "loc_servitude": _read("fbi_locations_servitude.csv", lambda p: pd.read_csv(p, encoding="utf-8-sig")),
        "loc_sex_acts": _read("fbi_locations_sex_acts.csv", lambda p: pd.read_csv(p, encoding="utf-8-sig")),
    }

    tracts = None
    geo_path = DATA_DIR / "tracts.geojson"
    if geo_path.exists():
        tracts = json.loads(geo_path.read_text())

    if not poi.empty:
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={"longitude": "lng", "latitude": "lat"})
        poi["type"] = poi["type"].astype(str).str.lower()
        poi = poi[poi["type"].isin(KNOWN_TYPES)]
        poi = poi[poi["name"].notna() & (poi["name"] != "Unnamed")]
        poi = poi.dropna(subset=["lat", "lng"]).reset_index(drop=True)
        for col in ("address", "county_name"):
            if col not in poi:
                poi[col] = ""
        poi["address"] = poi["address"].fillna("")
        poi["county_name"] = poi["county_name"].fillna("")

    return poi, census, fbi, tracts


# ==========================================
# 2. PROFILE MATCH SCORE (0-10)
# ==========================================
@st.cache_data(show_spinner=False)
def score_locations(poi: pd.DataFrame, servitude: pd.Series, sex_acts: pd.Series):
    """Vectorised score: venue (max 6) + area vulnerability (max 3) + statewide trend (max 1)."""
    df = poi.copy()

    # A. Statewide FBI trend: +1 if VA averaged >5 offenses/month over the last 6 months
    combined = servitude.add(sex_acts, fill_value=0).sort_index()
    recent_avg = float(combined.tail(6).mean()) if not combined.empty else 0.0
    trend_pts = TREND_MAX if recent_avg > 5 else 0.0

    # B. Venue profile
    df["venue_pts"] = DEFAULT_VENUE_WEIGHT
    for pattern, weight in reversed(VENUE_WEIGHTS):
        df.loc[df["type"].str.contains(pattern, regex=True), "venue_pts"] = weight

    # C. Area vulnerability (tract-level 0-1 index from the data pipeline)
    has_area = "vulnerability" in df.columns and df["vulnerability"].notna().any()
    vuln = df["vulnerability"].fillna(0.5) if has_area else pd.Series(0.5, index=df.index)
    df["area_pts"] = (vuln.clip(0, 1) * AREA_MAX).round(1)

    df["trend_pts"] = trend_pts
    df["score"] = (df["venue_pts"] + df["area_pts"] + df["trend_pts"]).clip(upper=10).round(1)

    df["tier"], df["color"], df["icon"] = TIERS[-1][1], TIERS[-1][2], TIERS[-1][3]
    for min_score, label, color, icon in reversed(TIERS[:-1]):
        hit = df["score"] >= min_score
        df.loc[hit, ["tier", "color", "icon"]] = [label, color, icon]

    return df, combined, recent_avg, trend_pts, has_area


# ==========================================
# 3. REVIEW KEYWORD CHECK (SerpAPI)
# ==========================================
def _serp_key():
    try:
        return st.secrets["SERP_KEY"]
    except Exception:
        return None


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def review_keyword_check(name: str, lat: float, lng: float):
    """Find the place on Google Maps near its coordinates and scan its recent reviews."""
    from serpapi import GoogleSearch

    key = _serp_key()
    res = GoogleSearch(
        {"engine": "google_maps", "type": "search", "q": name,
         "ll": f"@{lat},{lng},17z", "api_key": key}
    ).get_dict()
    if "error" in res and "place_results" not in res and "local_results" not in res:
        return {"error": res["error"]}

    place = res.get("place_results") or (res.get("local_results") or [None])[0]
    if not place or not place.get("data_id"):
        return {"error": "No matching Google Maps listing found."}

    reviews = GoogleSearch(
        {"engine": "google_maps_reviews", "data_id": place["data_id"], "api_key": key}
    ).get_dict().get("reviews", [])

    pattern = re.compile(r"\b(" + "|".join(map(re.escape, REVIEW_FLAGS)) + r")\b", re.I)
    hits = []
    for r in reviews:
        text = r.get("snippet") or ""
        found = sorted({m.lower() for m in pattern.findall(text)})
        if found:
            hits.append({"keywords": found, "text": text, "date": r.get("date", "")})

    return {
        "matched_title": place.get("title", ""),
        "matched_address": place.get("address", ""),
        "rating": place.get("rating"),
        "reviews_checked": len(reviews),
        "hits": hits,
    }


# ==========================================
# 4. LOAD + SIDEBAR
# ==========================================
poi_df, census_df, fbi, tracts_geo = load_data()

st.sidebar.title("🛡️ NOVA Profile Explorer")

if poi_df.empty:
    st.title("🛡️ NOVA Risk Profile Explorer")
    st.warning("📡 Location data isn't available yet. Run the data workflow from the repo's Actions tab.")
    st.stop()

scored, monthly, recent_avg, trend_pts, has_area = score_locations(
    poi_df, _fbi_series(fbi["servitude"]), _fbi_series(fbi["sex_acts"])
)

st.sidebar.metric(
    "Statewide FBI trend points", f"+{trend_pts:.0f}",
    help=f"Virginia averaged {recent_avg:.1f} trafficking offenses/month over the last 6 reported months "
         "(+1 when above 5). Applies equally to every location.",
)

st.sidebar.subheader("Filters")
min_score = st.sidebar.slider("Minimum profile score", 1.0, 10.0, 5.0, 0.5)

type_counts = scored["type"].value_counts()
all_types = sorted(type_counts.index)
selected_types = st.sidebar.multiselect(
    "Venue types", all_types, default=all_types,
    format_func=lambda t: f"{t.replace('_', ' ')} ({type_counts[t]})",
)

counties = sorted(c for c in scored["county_name"].unique() if c)
selected_counties = (
    st.sidebar.multiselect("Counties / cities", counties, default=counties) if counties else []
)

show_area = st.sidebar.checkbox(
    "Show area vulnerability layer", value=False, disabled=tracts_geo is None,
    help=None if tracts_geo is not None else "Available after the data workflow next runs.",
)

mask = (scored["score"] >= min_score) & scored["type"].isin(selected_types)
if counties:
    mask &= scored["county_name"].isin(selected_counties)
final_df = scored[mask].sort_values("score", ascending=False)

st.sidebar.markdown("---")
st.sidebar.caption(DISCLAIMER)


def _label(i):
    r = final_df.loc[i]
    where = r["address"] or r["county_name"] or f"{r['lat']:.4f}, {r['lng']:.4f}"
    return f"{r['name']} · {where}"


# ==========================================
# 5. MAIN
# ==========================================
st.title("🛡️ NOVA Risk Profile Explorer")
st.info(DISCLAIMER, icon="⚖️")
if not has_area:
    st.caption(
        "ℹ️ Area vulnerability isn't in the current data yet, so every location gets the neutral "
        "1.5 area points. It fills in after the data workflow next runs."
    )

tab_map, tab_table, tab_trends, tab_method = st.tabs(["Map", "Table", "FBI trends", "How scoring works"])

with tab_map:
    col1, col2 = st.columns([3, 1])

    with col1:
        m = folium.Map(location=[38.85, -77.30], zoom_start=10, tiles="cartodb dark_matter",
                       prefer_canvas=True)

        if show_area and tracts_geo is not None:
            steps = ["#1a1f36", "#2c3a73", "#4b4fa8", "#7a52c7", "#b04fc4"]

            def _area_style(feature):
                v = feature["properties"].get("vulnerability")
                fill = steps[min(int((v or 0) * len(steps)), len(steps) - 1)] if v is not None else "#444"
                return {"fillColor": fill, "color": "#888", "weight": 0.3, "fillOpacity": 0.45}

            folium.GeoJson(
                tracts_geo, name="Area vulnerability", style_function=_area_style,
                tooltip=folium.GeoJsonTooltip(
                    fields=["NAME", "vulnerability"], aliases=["Tract", "Vulnerability (0–1)"]
                ),
            ).add_to(m)

        MAX_MARKERS = 2000
        shown = final_df.head(MAX_MARKERS)
        for r in shown.itertuples():
            popup = (
                f"<b>{html.escape(r.name)}</b><br>{html.escape(r.type.replace('_', ' '))}"
                f"{'<br>' + html.escape(r.address) if r.address else ''}<br>"
                f"Profile score: <b>{r.score} / 10</b> ({r.tier})<br>"
                f"<small>venue {r.venue_pts:g} · area {r.area_pts:g} · trend {r.trend_pts:g}</small><br>"
                f"<small><i>Fits the profile; not evidence of wrongdoing.</i></small>"
            )
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=7, color="white", weight=0.6,
                fill=True, fill_color=r.color, fill_opacity=0.85,
                tooltip=html.escape(r.name), popup=folium.Popup(popup, max_width=280),
            ).add_to(m)

        st_folium(m, height=560, use_container_width=True, returned_objects=[], key="nova_map")
        if len(final_df) > MAX_MARKERS:
            st.caption(f"Showing the {MAX_MARKERS:,} highest-scoring of {len(final_df):,} locations. "
                       "Raise the minimum score or narrow the filters to see the rest.")

    with col2:
        st.metric("Locations shown", f"{len(final_df):,}")
        loc = fbi["loc_sex_acts"]
        if not loc.empty:
            st.caption(f"Most common FBI-reported location (VA, commercial sex acts): **{loc.iloc[0]['key']}**")

        if not final_df.empty:
            st.subheader("Strongest profile matches")
            st.caption("Ranked by fit to the profile, not by evidence.")
            for _, row in final_df.head(10).iterrows():
                st.write(f"{row['icon']} **{row['name']}**")
                st.caption(f"{row['score']} / 10 · {row['type'].replace('_', ' ')}"
                           f"{' · ' + row['county_name'] if row['county_name'] else ''}")

    # --- Review keyword check ---
    st.markdown("---")
    st.subheader("🔎 Review keyword check")
    if final_df.empty:
        st.caption("No locations match the current filters.")
    elif not _serp_key():
        st.caption("Add `SERP_KEY` to the app's Streamlit secrets to enable review checks.")
    else:
        c1, c2 = st.columns([3, 1])
        target = c1.selectbox("Location", final_df.index, format_func=_label, label_visibility="collapsed")
        run = c2.button("Check recent reviews", width="stretch")
        row = final_df.loc[target]
        if run:
            with st.spinner("Checking Google Maps reviews…"):
                try:
                    st.session_state.setdefault("scans", {})[target] = review_keyword_check(
                        row["name"], float(row["lat"]), float(row["lng"])
                    )
                except Exception as e:
                    st.session_state.setdefault("scans", {})[target] = {"error": str(e)}

        result = st.session_state.get("scans", {}).get(target)
        if result:
            if "error" in result:
                st.warning(f"Review check failed: {result['error']}")
            else:
                rating = f" · ★ {result['rating']}" if result.get("rating") else ""
                st.caption(
                    f"Matched Google listing: **{result['matched_title']}** {result['matched_address']}{rating} · "
                    f"{result['reviews_checked']} most recent reviews checked. "
                    "Confirm this is the right business before reading anything into it."
                )
                if not result["hits"]:
                    st.success("None of the watch keywords appeared in the reviews checked.")
                else:
                    st.warning(
                        f"Watch keywords appeared in {len(result['hits'])} review(s). These phrases are "
                        "common in ordinary reviews too (\"cash only\", \"after hours\"), so read them in context."
                    )
                    for h in result["hits"]:
                        text = html.escape(h["text"])
                        for k in h["keywords"]:
                            text = re.sub(rf"\b({re.escape(k)})\b", r"<mark>\1</mark>", text, flags=re.I)
                        st.markdown(
                            f"> {text}  \n<small>{html.escape(h['date'])} · {', '.join(h['keywords'])}</small>",
                            unsafe_allow_html=True,
                        )

with tab_table:
    cols = ["name", "type", "county_name", "address", "score", "tier", "venue_pts", "area_pts", "trend_pts", "lat", "lng"]
    table = final_df[[c for c in cols if c in final_df]].rename(columns={
        "county_name": "county", "venue_pts": "venue", "area_pts": "area", "trend_pts": "trend"})
    st.dataframe(
        table, hide_index=True, width="stretch",
        column_config={"score": st.column_config.ProgressColumn("score", min_value=0, max_value=10, format="%.1f")},
    )
    st.download_button(
        "Download CSV", table.to_csv(index=False).encode(), "nova_profile_matches.csv", "text/csv"
    )
    st.caption(DISCLAIMER)

with tab_trends:
    if not monthly.empty:
        trend = pd.DataFrame({
            "Involuntary servitude": _fbi_series(fbi["servitude"]),
            "Commercial sex acts": _fbi_series(fbi["sex_acts"]),
        }).fillna(0)
        st.subheader("Virginia human trafficking offenses per month (FBI)")
        st.line_chart(trend)
    lc1, lc2 = st.columns(2)
    for col, key, title in [(lc1, "loc_sex_acts", "Commercial sex acts"), (lc2, "loc_servitude", "Involuntary servitude")]:
        d = fbi[key]
        if not d.empty:
            col.subheader(f"Where offenses occurred: {title.lower()}")
            col.bar_chart(d.set_index("key")["value"], horizontal=True)
    st.caption("Source: FBI Crime Data Explorer, Virginia. Statewide figures, not specific to any location on the map.")

with tab_method:
    st.markdown(f"""
Each location gets a **profile score from 0 to 10**: how closely it matches the kinds of places
and conditions that show up in FBI trafficking data. It is a prioritization aid, not a finding.

| Part | Points | What it measures |
|---|---|---|
| Venue type | up to 6 | Hotels, motels, guest houses, spas and massage businesses get 6 (most common FBI-reported locations), residences 4, everything else 1. |
| Area vulnerability | up to 3 | Census-tract index from median household income, share of renters without a vehicle, and poverty rate (ACS 5-year), each ranked against other NoVA tracts. |
| Statewide trend | up to 1 | +1 for every location when Virginia averaged more than 5 trafficking offenses per month over the last 6 reported months. |

Score tiers: **8+** strong match · **5–8** moderate · **below 5** weak.

**Limitations to keep in mind**
- Venue type carries most of the score, so nearly every hotel and massage business scores highly. The score says nothing about how any individual business operates.
- Area indicators describe neighborhoods, not businesses.
- The FBI trend is statewide and identical for every location.
- The review check only reads a handful of recent public reviews and looks for keywords that also appear in ordinary reviews.
- Locations come from OpenStreetMap and can be missing, closed or mislabeled.

{DISCLAIMER}
""")
