import streamlit as st
import pandas as pd
import numpy as np
import requests
import folium
import time
from streamlit_folium import st_folium
from folium.plugins import HeatMap
from sklearn.cluster import DBSCAN

# ================================
# CONFIG
# ================================
st.set_page_config(page_title="OSINT Intelligence Dashboard", layout="wide")

LAT = 38.85
LNG = -77.30

st.title("🗺️ OSINT Intelligence Dashboard")

# ================================
# SESSION STATE (fallback safety)
# ================================
if "last_live_data" not in st.session_state:
    st.session_state.last_live_data = None

if "fallback_data" not in st.session_state:
    np.random.seed(42)
    st.session_state.fallback_data = pd.DataFrame({
        "name": [f"Simulated Location {i}" for i in range(40)],
        "lat": LAT + np.random.uniform(-0.08, 0.08, 40),
        "lng": LNG + np.random.uniform(-0.08, 0.08, 40),
        "type": np.random.choice(
            ["hotel", "motel", "bar", "nightclub", "cafe", "restaurant", "spa", "massage"],
            40
        ),
        "city": "Simulated Region",
        "street": "Simulated Area",
        "source": "Synthetic Model",
    })

# ================================
# CATEGORY BASE RISK
# ================================
BASE_WEIGHTS = {
    "hotel": 2.0,
    "motel": 2.2,
    "bar": 1.5,
    "nightclub": 2.0,
    "restaurant": 0.8,
    "cafe": 0.6,
    "spa": 2.5,
    "massage": 2.8,
}

# ================================
# FETCH DATA (your original logic)
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
            r = requests.post(url, data=query, timeout=15)
            data = r.json()

            rows = []
            for el in data.get("elements", []):
                tags = el.get("tags", {})

                lat = el.get("lat") or el.get("center", {}).get("lat")
                lng = el.get("lon") or el.get("center", {}).get("lon")

                if lat is None or lng is None:
                    continue

                category = tags.get("amenity") or tags.get("tourism") or tags.get("shop") or "unknown"

                rows.append({
                    "name": tags.get("name", "Unnamed"),
                    "lat": lat,
                    "lng": lng,
                    "type": category,
                    "city": tags.get("addr:city", "Unknown"),
                    "street": tags.get("addr:street", "Unknown"),
                    "source": "OpenStreetMap",
                })

            df = pd.DataFrame(rows)

            if not df.empty:
                return df, f"Live data from {url}"

        except Exception:
            continue

    return pd.DataFrame(), "fallback"

# ================================
# LOAD
# ================================
with st.spinner("Fetching OSINT data..."):
    df_raw, status = fetch_data()

if df_raw.empty:
    if st.session_state.last_live_data is not None:
        df_raw = st.session_state.last_live_data.copy()
        source = "Last Live Data"
    else:
        df_raw = st.session_state.fallback_data.copy()
        source = "Fallback Data"
else:
    st.session_state.last_live_data = df_raw.copy()
    source = "Live OSM Data"

st.sidebar.caption(f"Status: {status}")
st.caption(f"Source: {source}")

# ================================
# PROCESS (SAFE RISK MODEL)
# ================================
def process(df):
    df = df.copy()

    # clustering
    if len(df) > 3:
        coords = df[["lat", "lng"]].to_numpy()
        db = DBSCAN(eps=0.01, min_samples=3).fit(coords)
        df["cluster"] = db.labels_
    else:
        df["cluster"] = -1

    risks = []

    for i, row in df.iterrows():
        lat = row["lat"]
        lng = row["lng"]
        t = str(row["type"]).lower()

        base = BASE_WEIGHTS.get(t, 0.5)

        nearby = df[
            ((df["lat"] - lat).abs() < 0.015) &
            ((df["lng"] - lng).abs() < 0.015)
        ]

        density = min(len(nearby) / 10, 3)

        types = set(nearby["type"].astype(str).str.lower())

        combo = 0
        if {"hotel", "motel"} & types and {"bar", "nightclub"} & types:
            combo += 2.0
        if {"hotel", "motel"} & types and {"spa", "massage"} & types:
            combo += 1.5

        cluster_bonus = 0
        if row["cluster"] != -1:
            cluster_size = (df["cluster"] == row["cluster"]).sum()
            cluster_bonus = min(cluster_size * 0.2, 2)

        risk = base + density + combo + cluster_bonus
        risks.append(risk)

    df["risk"] = risks
    return df

df = process(df_raw)

# ================================
# FILTERS
# ================================
types = sorted(df["type"].unique())

selected = st.sidebar.multiselect("Category", types, default=types)
min_risk = st.sidebar.slider("Min Risk", 0.0, 10.0, 0.0)

filtered = df[
    (df["type"].isin(selected)) &
    (df["risk"] >= min_risk)
]

st.write("Points:", len(filtered))

# ================================
# MAP
# ================================
m = folium.Map(location=[LAT, LNG], zoom_start=11)

if not filtered.empty:
    HeatMap([[r.lat, r.lng, r.risk] for r in filtered.itertuples()], radius=18).add_to(m)

    for r in filtered.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=5,
            popup=f"{r.name} | Risk {round(r.risk,2)}",
            fill=True,
        ).add_to(m)

st_folium(m, width=1200, height=700)
