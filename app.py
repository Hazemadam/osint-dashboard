import re
import numpy as np
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from serpapi import GoogleSearch

# ==========================================
# 1. CONFIG
# ==========================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

try:
    SERP_KEY = st.secrets["SERP_KEY"]
except:
    st.error("Missing SERP_KEY in Streamlit secrets")
    st.stop()

# ==========================================
# 2. LOAD DATA
# ==========================================
@st.cache_data(ttl=3600)
def load_all_intel():
    USER, REPO = "Hazemadam", "osint-dashboard"
    base = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/"

    try:
        poi = pd.read_parquet(f"{base}nova_data.parquet")
        census = pd.read_parquet(f"{base}vulnerability_data.parquet")
        s_trend = pd.read_csv(f"{base}fbi_servitude.csv")
        x_trend = pd.read_csv(f"{base}fbi_sex_acts.csv")
        l_sex = pd.read_csv(f"{base}fbi_locations_sex_acts.csv")
        l_serv = pd.read_csv(f"{base}fbi_locations_servitude.csv")

        poi.columns = [c.lower().strip() for c in poi.columns]
        census.columns = [c.lower().strip() for c in census.columns]

        if "longitude" in poi.columns:
            poi = poi.rename(columns={"longitude": "lng", "latitude": "lat"})

        return poi, census, s_trend, x_trend, l_sex, l_serv
    except Exception as e:
        st.error(f"Data load error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

poi_df, census_df, serv_trend, sex_trend, loc_sex, loc_serv = load_all_intel()

# ==========================================
# 3. HELPERS
# ==========================================
def clean(x):
    return re.sub(r"\s+", " ", str(x).lower()).strip()

def clean_county(x):
    return clean(x).replace(" county", "").replace(" city", "")

# ==========================================
# 4. THREAT ENGINE (DYNAMIC TIERS)
# ==========================================
def run_threat_assessment(poi, census, s_trend, x_trend):
    if poi.empty:
        return pd.DataFrame(), 1.0

    # Trend
    trend_vals = pd.concat([
        pd.to_numeric(s_trend.iloc[0, 1:], errors="coerce") if not s_trend.empty else pd.Series(dtype=float),
        pd.to_numeric(x_trend.iloc[0, 1:], errors="coerce") if not x_trend.empty else pd.Series(dtype=float)
    ]).dropna()

    trend_mean = trend_vals.tail(6).mean() if not trend_vals.empty else 0
    multiplier = float(np.clip(0.95 + trend_mean / 25, 0.95, 1.1))

    # County normalization
    county_map = {}
    if not census.empty:
        c = census.copy()
        c["key"] = c["county"].map(clean_county)
        series = c.groupby("key")["vulnerability_score"].mean()

        if series.max() != series.min():
            series = (series - series.min()) / (series.max() - series.min())
        else:
            series = series * 0 + 0.5

        county_map = series.to_dict()

    scores = []

    for _, row in poi.iterrows():
        v_type = clean(row.get("type", ""))
        county = clean_county(row.get("county", "fairfax"))

        # Venue score
        if any(x in v_type for x in ["hotel", "motel", "spa", "massage"]):
            v = 45
        elif any(x in v_type for x in ["apartment", "residential"]):
            v = 30
        elif any(x in v_type for x in ["bar", "club"]):
            v = 25
        elif any(x in v_type for x in ["warehouse", "industrial"]):
            v = 15
        else:
            v = 5

        # County
        c_score = 25 * county_map.get(county, 0.3)

        # Trend
        t_score = min(trend_mean, 10)

        raw = (v + c_score + t_score) * (0.9 + (multiplier - 1) * 0.5)
        scores.append(float(np.clip(raw, 0, 100)))

    poi = poi.copy()
    poi["raw_score"] = scores

    # ======================================
    # 🔑 DYNAMIC THRESHOLDS (KEY FIX)
    # ======================================
    q_low = np.percentile(scores, 40)
    q_high = np.percentile(scores, 80)

    def classify(x):
        if x >= q_high:
            return "HIGH", "red"
        elif x >= q_low:
            return "MEDIUM", "orange"
        else:
            return "LOW", "blue"

    tiers = [classify(s) for s in scores]
    poi["level"] = [t[0] for t in tiers]
    poi["color"] = [t[1] for t in tiers]

    return poi, multiplier

# Run engine
processed_df, threat_multiplier = run_threat_assessment(
    poi_df, census_df, serv_trend, sex_trend
)

# ==========================================
# 5. SIDEBAR
# ==========================================
st.sidebar.title("Intel Controls")

levels = st.sidebar.multiselect(
    "Threat Levels",
    ["HIGH", "MEDIUM", "LOW"],
    default=["HIGH", "MEDIUM", "LOW"]
)

types = sorted(processed_df["type"].dropna().unique())

selected_types = st.sidebar.multiselect(
    "Venue Types",
    types,
    default=types
)

final_df = processed_df[
    (processed_df["level"].isin(levels)) &
    (processed_df["type"].isin(selected_types))
]

# ==========================================
# 6. MAP
# ==========================================
st.title("NOVA Risk Map")

m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")

for r in final_df.itertuples():
    radius = 6 if r.level == "LOW" else 8 if r.level == "MEDIUM" else 10

    folium.CircleMarker(
        location=[r.lat, r.lng],
        radius=radius,
        color="white",
        weight=0.5,
        fill=True,
        fill_color=r.color,
        fill_opacity=0.85,
        popup=f"{r.name}<br>{r.level} ({round(r.raw_score,1)})"
    ).add_to(m)

st_folium(m, width=900, height=550)

# ==========================================
# 7. METRICS
# ==========================================
col1, col2, col3 = st.columns(3)

col1.metric("Targets", len(final_df))
col2.metric("Avg Score", round(final_df["raw_score"].mean(), 1) if not final_df.empty else 0)
col3.metric("Multiplier", round(threat_multiplier, 2))
