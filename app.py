import streamlit as st
import pandas as pd
import numpy as np
import requests
import folium
import time
from streamlit_folium import st_folium
from folium.plugins import HeatMap

# ================================
# CONFIG
# ================================
st.set_page_config(
    page_title="OSINT Intelligence Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

LAT = 38.85
LNG = -77.30

st.title("🧠 OSINT Spatial Intelligence Dashboard")

# ================================
# SESSION STATE
# ================================
if "last_live_data" not in st.session_state:
    st.session_state.last_live_data = None

if "fallback_data" not in st.session_state:
    np.random.seed(42)
    st.session_state.fallback_data = pd.DataFrame({
        "name": [f"Simulated Location {i}" for i in range(50)],
        "lat": LAT + np.random.uniform(-0.08, 0.08, 50),
        "lng": LNG + np.random.uniform(-0.08, 0.08, 50),
        "type": np.random.choice(
            ["hotel", "motel", "bar", "nightclub", "cafe", "restaurant", "spa", "massage"], 50
        ),
        "city": "Simulated Region",
        "street": "Simulated Area",
        "source": "Synthetic Model",
    })

# ================================
# DATA FETCH
# ================================
@st.cache_data(ttl=600)
def fetch_data():
    query = """
    [out:json][timeout:20];
    (
      nwr["tourism"~"hotel|motel"](38.6,-77.6,39.1,-77.0);
      nwr["amenity"~"bar|nightclub|cafe|restaurant|spa"](38.6,-77.6,39.1,-77.0);
      nwr["shop"="massage"](38.6,-77.6,39.1,-77.0);
    );
    out center;
    """

    urls = [
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass-api.de/api/interpreter",
    ]

    for url in urls:
        try:
            r = requests.post(url, data=query, timeout=20)
            r.raise_for_status()
            data = r.json()

            rows = []
            for el in data.get("elements", []):
                tags = el.get("tags", {})
                lat = el.get("lat") or el.get("center", {}).get("lat")
                lng = el.get("lon") or el.get("center", {}).get("lon")

                if lat is None or lng is None:
                    continue

                rows.append({
                    "name": tags.get("name", "Unnamed"),
                    "lat": lat,
                    "lng": lng,
                    "type": (
                        tags.get("amenity")
                        or tags.get("tourism")
                        or tags.get("shop")
                        or "unknown"
                    ),
                    "city": tags.get("addr:city", "Unknown"),
                    "street": tags.get("addr:street", "Unknown"),
                })

            df = pd.DataFrame(rows)
            if not df.empty:
                return df, "Live OSM data"

        except:
            continue

    return pd.DataFrame(), "Fallback used"


# ================================
# LOAD
# ================================
df_raw, status = fetch_data()

if df_raw.empty:
    df_raw = st.session_state.fallback_data.copy()

st.caption(f"Data source: {status}")

# ================================
# OSINT RISK ENGINE (MULTI-LAYER)
# ================================
CATEGORY_WEIGHTS = {
    "hotel": 2.0,
    "motel": 2.2,
    "nightclub": 1.8,
    "bar": 1.3,
    "spa": 2.4,
    "massage": 2.6,
    "restaurant": 0.8,
    "cafe": 0.6,
    "shop": 0.4,
}

HIGH_RISK = {"hotel", "motel", "nightclub", "bar", "spa", "massage"}


def crime_score(lat, lng):
    return max(0, 3 - abs(lat - LAT) * 50)


def temporal_score(df, row):
    nearby = df[
        ((df["lat"] - row["lat"]).abs() < 0.02) &
        ((df["lng"] - row["lng"]).abs() < 0.02)
    ]
    return min(len(nearby) / 6, 3)


def baseline_score(df, row):
    local = len(df[
        ((df["lat"] - row["lat"]).abs() < 0.02) &
        ((df["lng"] - row["lng"]).abs() < 0.02)
    ])
    return max(0, local / 10)


def incident_score():
    return np.random.uniform(0, 1.2)


def compute_risk(row, df):
    t = str(row["type"]).lower()

    osm = CATEGORY_WEIGHTS.get(t, 0.3)

    nearby = df[
        ((df["lat"] - row["lat"]).abs() < 0.015) &
        ((df["lng"] - row["lng"].abs()) < 0.015)
    ]

    density = min(len(nearby) / 8, 3)

    types = set(nearby["type"].astype(str).str.lower())

    osm_bonus = 0
    if {"hotel", "motel"} & types and {"bar", "nightclub"} & types:
        osm_bonus += 2.5

    crime = crime_score(row["lat"], row["lng"])
    temporal = temporal_score(df, row)
    baseline = baseline_score(df, row)
    incidents = incident_score()

    return (
        osm * 0.4 +
        density * 0.3 +
        osm_bonus * 0.3 +
        crime * 0.25 +
        temporal * 0.15 +
        baseline * 0.15 +
        incidents * 0.1
    )


# ================================
# PROCESS
# ================================
df = df_raw.copy()
df["type"] = df["type"].astype(str).str.lower()
df["risk"] = df.apply(lambda r: compute_risk(r, df), axis=1)

# ================================
# UI SIDEBAR (UPGRADED)
# ================================
st.sidebar.header("🎛️ Controls")

types = sorted(df["type"].unique())

selected_types = st.sidebar.multiselect(
    "Category Filter",
    types,
    default=types
)

risk_range = st.sidebar.slider("Risk Range", 0.0, 10.0, (0.0, 10.0))

show_heat = st.sidebar.checkbox("Heatmap", True)
show_points = st.sidebar.checkbox("Points", True)

# ================================
# FILTERED DATA
# ================================
filtered = df[
    (df["type"].isin(selected_types)) &
    (df["risk"] >= risk_range[0]) &
    (df["risk"] <= risk_range[1])
]

# ================================
# KPI DASHBOARD (NEW UI)
# ================================
col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Points", len(df))
col2.metric("Filtered Points", len(filtered))
col3.metric("Avg Risk", round(df["risk"].mean(), 2))
col4.metric("Max Risk", round(df["risk"].max(), 2))

st.divider()

# ================================
# TABLE + MAP LAYOUT
# ================================
left, right = st.columns([1, 2])

with left:
    st.subheader("📋 Data View")
    st.dataframe(
        filtered[["name", "type", "risk", "city", "street"]],
        use_container_width=True,
        height=600
    )

with right:
    st.subheader("🗺️ Risk Map")

    m = folium.Map(location=[LAT, LNG], zoom_start=11)

    if show_heat and not filtered.empty:
        heat = [[r.lat, r.lng, r.risk] for r in filtered.itertuples()]
        HeatMap(heat, radius=18).add_to(m)

    if show_points:
        for r in filtered.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=5,
                popup=f"{r.name} | Risk {r.risk:.2f}",
                fill=True,
                fill_opacity=0.7,
            ).add_to(m)

    st_folium(m, width=900, height=650)

# ================================
# FOOTER INSIGHT
# ================================
st.caption("OSINT pattern model: spatial clustering + crime proxy + baseline deviation + temporal simulation")
