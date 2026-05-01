import re
import numpy as np
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
from serpapi import GoogleSearch

# ==========================================
# 1. INITIAL CONFIG & DEFAULTS
# ==========================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

final_df = pd.DataFrame()
poi_df = pd.DataFrame()
census_df = pd.DataFrame()
serv_trend = pd.DataFrame()
sex_trend = pd.DataFrame()
loc_sex = pd.DataFrame()
loc_serv = pd.DataFrame()
threat_multiplier = 1.0
target = None

try:
    SERP_KEY = st.secrets["SERP_KEY"]
except:
    st.error("🔑 SERP_KEY missing in Streamlit Secrets!")
    st.stop()

@st.cache_data(ttl=3600)
def load_all_intel():
    USER, REPO = "Hazemadam", "osint-dashboard"
    base = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/"

    try:
        p = pd.read_parquet(f"{base}nova_data.parquet")
        c = pd.read_parquet(f"{base}vulnerability_data.parquet")

        f_serv = pd.read_csv(f"{base}fbi_servitude.csv")
        f_sex = pd.read_csv(f"{base}fbi_sex_acts.csv")
        l_sex = pd.read_csv(f"{base}fbi_locations_sex_acts.csv")
        l_serv = pd.read_csv(f"{base}fbi_locations_servitude.csv")

        p.columns = [col.lower().strip() for col in p.columns]
        c.columns = [col.lower().strip() for col in c.columns]

        if "longitude" in p.columns and "latitude" in p.columns:
            p = p.rename(columns={"longitude": "lng", "latitude": "lat"})

        return p, c, f_serv, f_sex, l_sex, l_serv
    except Exception as e:
        st.sidebar.error(f"📡 Data Link Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

poi_df, census_df, serv_trend, sex_trend, loc_sex, loc_serv = load_all_intel()

# ==========================================
# 2. INTELLIGENCE ENGINE (IMPROVED CALIBRATION)
# ==========================================
def normalize_text(x):
    return re.sub(r"\s+", " ", str(x).lower()).strip()

def normalize_county(x):
    x = normalize_text(x)
    x = x.replace(" county", "").replace(" city of ", "").replace(" city", "").strip()
    return x

def run_threat_assessment(poi, census, s_trend, x_trend, lsx, lsv):
    if poi.empty:
        return pd.DataFrame(), pd.Series(dtype=float), 1.0

    # Combine trend series safely
    trend_vals = pd.concat([
        pd.to_numeric(s_trend.iloc[0, 1:], errors="coerce") if not s_trend.empty else pd.Series(dtype=float),
        pd.to_numeric(x_trend.iloc[0, 1:], errors="coerce") if not x_trend.empty else pd.Series(dtype=float)
    ], ignore_index=True).dropna()

    recent = trend_vals.tail(min(6, len(trend_vals)))
    trend_mean = float(recent.mean()) if not recent.empty else 0.0
    trend_std = float(trend_vals.std(ddof=0)) if len(trend_vals) > 1 else 0.0

    # Keep the multiplier modest so it does not collapse the tiers
    multiplier = float(np.clip(0.95 + (trend_mean / 20.0) + (trend_std / 50.0), 0.95, 1.15))

    # Build normalized county risk lookup: 0.0 to 1.0
    county_risk = {}
    if not census.empty and {"county", "vulnerability_score"}.issubset(census.columns):
        c = census.copy()
        c["county_key"] = c["county"].map(normalize_county)
        county_series = c.groupby("county_key")["vulnerability_score"].mean()

        if county_series.notna().any():
            mn, mx = county_series.min(), county_series.max()
            if pd.notna(mn) and pd.notna(mx) and mx != mn:
                county_risk = ((county_series - mn) / (mx - mn)).to_dict()
            else:
                county_risk = county_series.apply(lambda _: 0.5).to_dict()

    scores, colors, levels = [], [], []

    for _, row in poi.iterrows():
        v_type = normalize_text(row.get("type", ""))
        county_key = normalize_county(row.get("county", "fairfax"))

        # Venue component: 0–60
        if any(x in v_type for x in ["motel", "hotel", "spa", "massage"]):
            venue_score = 55
        elif any(x in v_type for x in ["apartment", "residential", "home", "studio"]):
            venue_score = 40
        elif any(x in v_type for x in ["bar", "club", "nightclub", "strip"]):
            venue_score = 35
        elif any(x in v_type for x in ["warehouse", "industrial", "storage", "vacant"]):
            venue_score = 25
        else:
            venue_score = 15

        # County component: 0–30
        county_score = 15 + 15 * float(county_risk.get(county_key, 0.5))

        # Regional component: 0–10
        regional_score = float(np.clip(trend_mean, 0, 10))

        raw = (venue_score + county_score + regional_score) * multiplier
        raw = float(np.clip(raw, 0, 100))

        scores.append(raw)

        if raw >= 70:
            levels.append("HIGH")
            colors.append("red")
        elif raw >= 35:
            levels.append("MEDIUM")
            colors.append("orange")
        else:
            levels.append("LOW")
            colors.append("blue")

    poi = poi.copy()
    poi["raw_score"] = scores
    poi["color"] = colors
    poi["level"] = levels

    return poi, trend_vals, multiplier

# ==========================================
# 3. SIDEBAR CONTROLS
# ==========================================
st.sidebar.title("🛡️ NOVA Intel Command")

if not poi_df.empty and not serv_trend.empty:
    processed_df, master_trend, threat_multiplier = run_threat_assessment(
        poi_df, census_df, serv_trend, sex_trend, loc_sex, loc_serv
    )

    st.sidebar.metric("Regional Multiplier", f"{round(threat_multiplier, 2)}x")

    st.sidebar.subheader("Filter by Threat")
    selected_levels = st.sidebar.multiselect(
        "Threat Tiers", ["HIGH", "MEDIUM", "LOW"], default=["HIGH", "MEDIUM", "LOW"]
    )

    all_types = sorted(processed_df["type"].dropna().unique())
    selected_types = st.sidebar.multiselect(
        "Venue Categories", all_types, default=all_types
    )

    final_df = processed_df[
        (processed_df["level"].isin(selected_levels)) &
        (processed_df["type"].isin(selected_types))
    ]

    if not final_df.empty:
        st.sidebar.markdown("---")
        target = st.sidebar.selectbox("Select Target for OSINT", sorted(final_df["name"].dropna().unique()))
        if st.sidebar.button("Run Deep Scan"):
            with st.spinner("Scanning for Red Flags..."):
                search = GoogleSearch({
                    "engine": "google_maps",
                    "q": f"{target} Northern Virginia",
                    "api_key": SERP_KEY
                })
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id") if "local_results" in res else None

                if d_id:
                    revs = GoogleSearch({
                        "engine": "google_maps_reviews",
                        "data_id": d_id,
                        "api_key": SERP_KEY
                    }).get_dict().get("reviews", [])

                    flags = ["buzzer", "locked", "cash only", "scared", "after hours", "back door"]
                    found = [f for r in revs for f in flags if f in str(r.get("snippet", "")).lower()]
                    st.session_state["scan_results"] = {target: list(set(found)) if found else ["CLEAR"]}
else:
    st.sidebar.warning("📡 Connecting to GitHub data sources...")

# ==========================================
# 4. MAIN INTERFACE
# ==========================================
st.title("🛡️ NOVA Risk Intelligence")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")

    if not final_df.empty:
        for r in final_df.itertuples():
            radius = 6 if r.level == "LOW" else 8 if r.level == "MEDIUM" else 10
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=radius,
                color="white",
                weight=0.7,
                fill=True,
                fill_color=r.color,
                fill_opacity=0.85,
                popup=f"<b>{r.name}</b><br>Score: {round(r.raw_score, 1)}<br>Tier: {r.level}"
            ).add_to(m)

    st_folium(m, width=900, height=550, key="nova_v13_final")

    if "scan_results" in st.session_state and target in st.session_state["scan_results"]:
        st.markdown("---")
        st.subheader(f"📄 Intelligence Report: {target}")
        res_list = st.session_state["scan_results"][target]
        if "CLEAR" in res_list:
            st.success("✅ No linguistic red-flags detected in local metadata.")
        else:
            st.error(f"🚩 **Metadata Flags Detected:** {', '.join(res_list)}")

with col2:
    st.metric("Visible Targets", len(final_df))

    if not loc_sex.empty:
        st.info(f"**FBI Primary Vector:** {loc_sex.iloc[0]['key']}")

    if not final_df.empty:
        st.markdown("---")
        st.subheader("⚠️ Priority Watchlist")
        watchlist = final_df.sort_values("raw_score", ascending=False).head(10)

        for _, row in watchlist.iterrows():
            icon = "🔴" if row["level"] == "HIGH" else ("🟠" if row["level"] == "MEDIUM" else "🔵")
            st.write(f"{icon} **{row['name']}**")
            st.caption(f"Score: {round(row['raw_score'], 1)} | {row['type']}")
