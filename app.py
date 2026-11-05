import html
import json
import re
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import deep_dive as dd

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
# 3. BUSINESS DEEP DIVE (SerpAPI)
# ==========================================
def _serp_key():
    try:
        return st.secrets["SERP_KEY"]
    except Exception:
        return None


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def business_deep_dive(name: str, lat: float, lng: float, pages: int):
    return dd.fetch_business(name, lat, lng, pages, _serp_key())


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

tab_map, tab_dive, tab_table, tab_trends, tab_method = st.tabs(
    ["Map", "Business deep dive", "Table", "FBI trends", "How scoring works"]
)

with tab_map:
    col1, col2 = st.columns([3, 1])

    with col1:
        # CARTO's free basemaps now require an API key, so use keyless tile sources.
        esri = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"
        esri_attr = "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"
        m = folium.Map(location=[38.85, -77.30], zoom_start=10, tiles=None, prefer_canvas=True)
        folium.TileLayer(esri.format("World_Dark_Gray_Base"), attr=esri_attr, name="Dark",
                         max_zoom=16).add_to(m)
        folium.TileLayer("OpenStreetMap", name="Streets", show=False).add_to(m)
        folium.TileLayer(esri.format("World_Dark_Gray_Reference"), attr=esri_attr, name="Labels",
                         overlay=True, control=True, max_zoom=16).add_to(m)

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
        markers = folium.FeatureGroup(name="Locations").add_to(m)
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
            ).add_to(markers)

        if not shown.empty:
            m.fit_bounds([[shown["lat"].min(), shown["lng"].min()],
                          [shown["lat"].max(), shown["lng"].max()]], padding=(20, 20))
        folium.LayerControl(collapsed=True).add_to(m)
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

with tab_dive:
    st.subheader("🔎 Business deep dive")
    st.caption(
        "Pulls together everything public about one business: its profile score, the area it's in, "
        "nearby profile matches, its Google Maps listing and hours, and an analysis of its recent "
        "reviews. Business-level information only; it doesn't look up owners, staff or reviewers."
    )
    if final_df.empty:
        st.info("No locations match the current filters. Lower the minimum score in the sidebar.")
    else:
        target = st.selectbox("Business", final_df.index, format_func=_label,
                              help="Type to search. The list follows the sidebar filters.")
        row = final_df.loc[target]

        # --- Profile + area (free, from local data) ---
        a, b, c = st.columns(3)
        a.metric("Profile score", f"{row['score']} / 10", row["tier"], delta_color="off")
        b.metric("Venue type", row["type"].replace("_", " ").title(), f"{row['venue_pts']:g} of 6 pts",
                 delta_color="off")
        c.metric("Area vulnerability", f"{row['area_pts']:g} of 3 pts",
                 row["county_name"] or None, delta_color="off")

        tract = None
        if "geoid" in row and not census_df.empty and "geoid" in census_df:
            m_ = census_df[census_df["geoid"] == row["geoid"]]
            tract = m_.iloc[0] if not m_.empty else None
        if tract is not None:
            nova_inc = census_df["median_income"].median()
            nova_pov = census_df["poverty_rate"].median()
            inc = tract["median_income"]
            st.caption(
                f"**Census tract** {tract['NAME'].split(';')[0].split(',')[0]} · "
                f"median household income {'n/a' if pd.isna(inc) else f'${inc:,.0f}'} "
                f"(NoVA tract median ${nova_inc:,.0f}) · poverty rate "
                f"{'n/a' if pd.isna(tract['poverty_rate']) else f'{tract.poverty_rate:.0%}'} "
                f"(NoVA {nova_pov:.0%}) · renters without a car "
                f"{'n/a' if pd.isna(tract['no_vehicle_renter_share']) else f'{tract.no_vehicle_renter_share:.0%}'}"
            )

        dist = dd.haversine_m(row["lat"], row["lng"], scored["lat"].values, scored["lng"].values)
        near = scored.assign(distance_m=dist)
        near = near[(near["distance_m"] <= 1000) & (near.index != target) & (near["score"] >= 5)]
        near = near.sort_values("distance_m")
        nearby = near[["name", "type", "distance_m", "score"]].head(15).to_dict("records")
        with st.expander(f"Nearby profile matches within 1 km: {len(near)}", expanded=False):
            if near.empty:
                st.caption("None.")
            else:
                st.dataframe(
                    near[["name", "type", "distance_m", "score"]].head(15).rename(columns={"distance_m": "metres"}),
                    hide_index=True, width="stretch",
                    column_config={"metres": st.column_config.NumberColumn(format="%.0f")},
                )
                st.caption("Several matches close together can point to a corridor worth looking at as a whole.")

        # --- Google listing + reviews (SerpAPI) ---
        st.markdown("#### Google Maps listing & reviews")
        result = None
        if not _serp_key():
            st.caption("Add `SERP_KEY` to the app's Streamlit secrets to enable listing and review analysis.")
        else:
            c1, c2 = st.columns([3, 1])
            depth = c1.selectbox("Review depth", list(dd.REVIEW_DEPTHS), index=1,
                                 help="More reviews give a better picture but use more SerpAPI searches. "
                                      "Results are saved for a week, so re-running is free.")
            pages = dd.REVIEW_DEPTHS[depth]
            c2.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
            run = c2.button("Run deep dive", type="primary", width="stretch")
            key = (target, pages)
            if run:
                with st.spinner("Looking up the listing and reading reviews…"):
                    try:
                        st.session_state.setdefault("dives", {})[key] = business_deep_dive(
                            row["name"], float(row["lat"]), float(row["lng"]), pages)
                    except Exception as e:
                        st.session_state.setdefault("dives", {})[key] = {"error": str(e)}
            result = st.session_state.get("dives", {}).get(key)

        if result and "error" in result:
            st.warning(f"Deep dive failed: {result['error']}")
        elif result:
            L, H, R = result["listing"], result["hours"], result["reviews"]
            far = L["distance_m"] is not None and L["distance_m"] > 250
            msg = (f"Matched **{L['title']}**, {L['address']}"
                   + (f" ({L['distance_m']:.0f} m from the mapped location)" if L["distance_m"] is not None else ""))
            (st.warning if far else st.caption)(
                msg + (". That's far enough that it may be a different business; check before relying on it."
                       if far else ". Confirm this is the right business before reading anything into it."))

            l1, l2, l3, l4 = st.columns(4)
            l1.metric("Google rating", f"★ {L['rating']}" if L["rating"] else "n/a",
                      f"{L['review_total']:,} reviews" if L["review_total"] else None, delta_color="off")
            l2.metric("Category", L["category"] or "n/a")
            l3.metric("Status", L["open_state"].split("⋅")[0].strip() if L["open_state"] else "n/a")
            l4.metric("Price", L["price"] or "n/a")
            st.caption(f"Website: {L['website'] or 'none listed'} · Phone: {L['phone'] or 'none listed'}")

            st.markdown("##### Signals")
            st.caption("Each is common at ordinary businesses. Look at them together and in context.")
            sig_rows = [{"Signal": n, "Present": "Yes" if p else ("Unknown" if p is None else "No"), "Detail": d}
                        for n, p, d in dd.signals(result)]
            st.dataframe(pd.DataFrame(sig_rows), hide_index=True, width="stretch")

            h1, h2 = st.columns(2)
            with h1:
                st.markdown("##### Hours")
                if H["known"]:
                    st.dataframe(pd.DataFrame(
                        [{"Day": d.title(), "Hours": h, "Late": "🌙" if d in H["late_days"] else ""}
                         for d, h in H["days"].items()]), hide_index=True, width="stretch")
                else:
                    st.caption("No hours on the listing.")
            with h2:
                st.markdown("##### Ratings in the reviews read")
                if R["count"]:
                    st.bar_chart(pd.Series(R["ratings"], name="reviews").rename(lambda s: f"{s}★"))
                    st.caption(f"{R['count']} reviews from {R['oldest']} to {R['newest']}.")
                else:
                    st.caption("No reviews returned.")

            if len(R["months"]) > 1:
                st.markdown("##### Review activity by month")
                st.bar_chart(pd.Series(R["months"], name="reviews"))
                st.caption("Bursts of reviews, or a sudden stop, can be worth a closer look.")

            st.markdown(f"##### Reviews with indicator language: {len(R['hits'])} of {R['count']}")
            if not R["hits"]:
                st.success("None of the indicator phrases appeared in the reviews read.")
            else:
                st.caption("Phrases are highlighted. Many have innocent meanings, so read the whole review.")
                themes = sorted({t for h in R["hits"] for t in h["themes"]})
                pick = st.multiselect("Themes", themes, default=themes, label_visibility="collapsed")
                for h in R["hits"]:
                    if not set(h["themes"]) & set(pick):
                        continue
                    phrases = [p for ps in h["themes"].values() for p in ps]
                    tags = " · ".join(h["themes"])
                    stars = f"{h['rating']:g}★" if isinstance(h["rating"], (int, float)) else ""
                    st.markdown(
                        f"> {dd.highlight(h['text'], phrases)}  \n"
                        f"<small>{html.escape(h['date'])} · {stars} · {html.escape(tags)}</small>",
                        unsafe_allow_html=True,
                    )
            st.caption(f"Fetched {result['fetched_at']} · {result['searches_used']} SerpAPI searches.")

        st.download_button(
            "Download profile (Markdown)",
            dd.report_markdown(row.to_dict(), result, nearby, DISCLAIMER).encode(),
            file_name=f"profile_{re.sub(r'[^A-Za-z0-9]+', '_', row['name']).strip('_')[:40]}.md",
            mime="text/markdown",
        )
        st.caption(DISCLAIMER)

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
- The business deep dive reads at most the ~50 newest public Google reviews. Its indicator phrases (grouped by theme, drawn from published anti-trafficking research) also appear in ordinary reviews, and their absence doesn't clear a business.
- The deep dive is business-level only: it doesn't look up owners, staff or reviewers.
- Locations come from OpenStreetMap and can be missing, closed or mislabeled.

{DISCLAIMER}
""")
