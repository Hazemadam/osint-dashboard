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
# STATE MANAGEMENT
# ================================
if "last_good_data" not in st.session_state:
    st.session_state.last_good_data = None

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
# DATA FETCH (ROBUST PIPELINE)
# ================================
@st.cache_data(ttl=600)
def fetch_data():
    query = """
    [out:json][timeout:25];
    (
      nwr["tourism"="hotel"];
      nwr["tourism"="motel"];
      nwr["amenity"="bar"];
      nwr["amenity"="nightclub"];
      nwr["amenity"="cafe"];
      nwr["amenity"="restaurant"];
      nwr["amenity"="spa"];
      nwr["shop"="massage"];
    )(38.6,-77.6,39.1,-77.0);
    out center;
    """

    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.openstreetmap.ru/api/interpreter",
    ]

    errors = []

    for url in endpoints:
        try:
            r = requests.post(
                url,
                data=query,
                headers={"Content-Type": "text/plain"},
                timeout=30
            )

            if r.status_code != 200:
                errors.append(f"{url} → HTTP {r.status_code}")
                continue

            data = r.json()
            elements = data.get("elements", [])

            if not elements:
                errors.append(f"{url} → empty response")
                continue

            rows = []

            for el in elements:
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

            if len(df) > 0:
                return df, f"Live OSM data from {url}"

            errors.append(f"{url} → parsed but empty dataset")

        except Exception as e:
            errors.append(f"{url} → {str(e)}")

    st.warning("Live data unavailable. Reasons:\n" + "\n".join(errors))

    return pd.DataFrame(), "fallback"


# ================================
# LOAD DATA (SMART FALLBACK SYSTEM)
# ================================
df_raw, status = fetch_data()

if df_raw.empty:
    if st.session_state.last_good_data is not None:
        df_raw = st.session_state.last_good_data.copy()
        data_source = "Cached last-good live dataset"
    else:
        df_raw = st.session_state.fallback_data.copy()
        data_source = "Synthetic fallback dataset"
else:
    st.session_state.last_good_data = df_raw.copy()
    data_source = "Live OpenStreetMap"

st.caption(f"Data source: {data_source}")


# ================================
# OSINT RISK ENGINE (STABLE VERSION)
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


def compute_risk(row, df):
    lat, lng = row["lat"], row["lng"]
    t = str(row["type"]).lower()

    base = CATEGORY_WEIGHTS.get(t, 0.3)

    nearby = df[
        ((df["lat"] - lat).abs() < 0.015) &
        ((df["lng"] - lng).abs() < 0.015)
    ]

    density = min(len(nearby) / 8, 3.0)

    types = set(nearby["type"].astype(str).str.lower())

    combo_bonus = 0
    if {"hotel", "motel"} & types and {"bar", "nightclub"} & types:
        combo_bonus += 2.5
    if {"hotel", "motel"} & types and {"spa", "massage"} & types:
        combo_bonus += 1.8

    cluster_bonus = min(sum(x in HIGH_RISK for x in types) * 0.4, 2.0)

    if len(nearby) < 3:
        density *= 0.7

    return float(base + density + combo_bonus + cluster_bonus)


# ================================
# PROCESS DATA
# ================================
df = df_raw.copy()
df["type"] = df["type"].astype(str).str.lower()
df["risk"] = df.apply(lambda r: compute_risk(r, df), axis=1)


# ================================
# FILTER UI
# ================================
st.sidebar.header("🎛️ Controls")

types = sorted(df["type"].unique())

selected_types = st.sidebar.multiselect(
    "Categories",
    types,
    default=types
)

min_risk = st.sidebar.slider("Minimum Risk", 0.0, 10.0, 0.0)

show_heat = st.sidebar.checkbox("Heatmap", True)
show_points = st.sidebar.checkbox("Points", True)


filtered = df[
    (df["type"].isin(selected_types)) &
    (df["risk"] >= min_risk)
]


# ================================
# KPI DASHBOARD
# ================================
col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Points", len(df))
col2.metric("Filtered Points", len(filtered))
col3.metric("Avg Risk", round(df["risk"].mean(), 2))
col4.metric("Max Risk", round(df["risk"].max(), 2))

st.divider()


# ================================
# TABLE + MAP
# ================================
left, right = st.columns([1, 2])

with left:
    st.subheader("📋 Data")
    st.dataframe(
        filtered[["name", "type", "risk", "city", "street"]],
        use_container_width=True,
        height=600
    )

with right:
    st.subheader("🗺️ Risk Map")

    m = folium.Map(location=[LAT, LNG], zoom_start=11)

    if show_heat and not filtered.empty:
        HeatMap(
            [[r.lat, r.lng, r.risk] for r in filtered.itertuples()],
            radius=18
        ).add_to(m)

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


st.caption("Hybrid OSINT model: OpenStreetMap + spatial clustering + pattern-based risk scoring + resilient fallback system")
