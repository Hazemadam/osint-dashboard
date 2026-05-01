import re
import numpy as np
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
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

# ==========================================
# 2. DATA LOADING
# ==========================================
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

        if "longitude" in p.columns:
            p = p.rename(columns={"longitude": "lng", "latitude": "lat"})

        return p, c, f_serv, f_sex, l_sex, l_serv
    except Exception as e:
        st.sidebar.error(f"📡 Data Link Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

poi_df, census_df, serv_trend, sex_trend, loc_sex, loc_serv = load_all_intel()

# ==========================================
# 3. HELPERS
# ==========================================
def normalize_text(x):
    return re.sub(r"\s+", " ", str(x).lower()).strip()

def normalize_county(x):
    x = normalize_text(x)
    return x.replace(" county", "").replace(" city", "").strip()

# ==========================================
# 4. THREAT ENGINE (FIXED)
# ==========================================
def run_threat_assessment(poi, census, s_trend, x_trend, lsx, lsv):
    if poi.empty:
        return pd.DataFrame(), pd.Series(dtype=float), 1.0

    # Trend calculation
    trend_vals = pd.concat([
        pd.to_numeric(s_trend.iloc[0, 1:], errors="coerce") if not s_trend.empty else pd.Series(dtype=float),
        pd.to_numeric(x_trend.iloc[0, 1:], errors="coerce") if not x_trend.empty else pd.Series(dtype=float)
    ], ignore_index=True).dropna()

    trend_mean = float(trend_vals.tail(6).mean()) if not trend_vals.empty else 0.0

    # Light multiplier (NOT overpowering)
    multiplier = float(np.clip(0.95 + trend_mean / 25.0, 0.95, 1.1))

    # Normalize county vulnerability (0–1)
    county_risk = {}
    if not census.empty and {"county", "vulnerability_score"}.issubset(census.columns):
        c = census.copy()
        c["county_key"] = c["county"].map(normalize_county)
        series = c.groupby("county_key")["vulnerability_score"].mean()

        if series.max() != series.min():
            series = (series - series.min()) / (series.max() - series.min())
        else:
            series = series * 0 + 0.5

        county_risk = series.to_dict()

    scores, colors, levels = [], [], []

    for _, row in poi.iterrows():
        v_type = normalize_text(row.get("type", ""))
        county_key = normalize_county(row.get("county", "fairfax"))

        # ---------- VENUE SCORE (KEY FIX) ----------
        if any(x in v_type for x in ["motel", "hotel", "spa", "massage"]):
            venue_score = 45
        elif any(x in v_type for x in ["apartment", "residential", "home", "studio"]):
            venue_score = 30
        elif any(x in v_type for x in ["bar", "club", "nightclub"]):
            venue_score = 25
        elif any(x in v_type for x in ["warehouse", "industrial", "vacant"]):
            venue_score = 15
        else:
            venue_score = 5  # 🔑 enables LOW tier

        # ---------- COUNTY SCORE ----------
        county_score = 25 * float(county_risk.get(county_key, 0.3))

        # ---------- TREND SCORE ----------
        regional_score = float(np.clip(trend_mean, 0, 10))

        # ---------- FINAL SCORE ----------
        raw = venue_score + county_score + regional_score

        # Light multiplier effect
        raw = raw * (0.9 + (multiplier - 1) * 0.5)

        raw = float(np.clip(raw, 0, 100))
        scores.append(raw)

        # ---------- TIERS ----------
        if raw >= 65:
            levels.append("HIGH")
            colors.append("red")
        elif raw >= 30:
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
# 5. SIDEBAR
# ==========================================
st.sidebar.title("🛡️ NOVA Intel Command")

if not poi_df.empty:
    processed_df, master_trend, threat_multiplier = run_threat_assessment(
        poi_df, census_df, serv_trend, sex_trend, loc_sex, loc_serv
    )

    st.sidebar.metric("Regional Multiplier", f"{round(threat_multiplier, 2)}x")

    selected_levels = st.sidebar.multiselect(
        "Threat Tiers", ["HIGH", "MEDIUM", "LOW"], default=["HIGH", "MEDIUM", "LOW"]
    )

    all_types = sorted(processed_df["type"].dropna().unique())

    # 🔑 FIX: show ALL types by default
    selected_types = st.sidebar.multiselect(
        "Venue Categories", all_types, default=all_types
    )

    final_df = processed_df[
        (processed_df["level"].isin(selected_levels)) &
        (processed_df["type"].isin(selected_types))
    ]

    if not final_df.empty:
        st.sidebar.markdown("---")
        target = st.sidebar.selectbox("Select Target", sorted(final_df["name"].dropna().unique()))

        if st.sidebar.button("Run Deep Scan"):
            with st.spinner("Scanning..."):
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

                    st.session_state["scan_results"] = {
                        target: list(set(found)) if found else ["CLEAR"]
                    }

# ==========================================
# 6. MAIN MAP
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
                popup=f"<b>{r.name}</b><br>Score: {round(r.raw_score,1)}<br>Tier: {r.level}"
            ).add_to(m)

    st_folium(m, width=900, height=550)

with col2:
    st.metric("Visible Targets", len(final_df))

    if not final_df.empty:
        st.markdown("---")
        st.subheader("⚠️ Priority Watchlist")

        watchlist = final_df.sort_values("raw_score", ascending=False).head(10)

        for _, row in watchlist.iterrows():
            icon = "🔴" if row["level"] == "HIGH" else ("🟠" if row["level"] == "MEDIUM" else "🔵")
            st.write(f"{icon} **{row['name']}**")
            st.caption(f"{round(row['raw_score'],1)} | {row['type']}")
