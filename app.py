import streamlit as st
import pandas as pd
import numpy as np
import requests
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap
from sklearn.cluster import DBSCAN

# ================================
# CONFIG
# ================================
st.set_page_config(page_title="OSINT Dashboard", layout="wide")

LAT = 38.85
LNG = -77.30

st.title("🗺️ OSINT Hotspot Dashboard (Stable Version)")

# ================================
# 1. DATA (cached - prevents flicker)
# ================================
@st.cache_data(ttl=600)
def fetch_data():
    query = """
    [out:json];
    (
      node["tourism"="hotel"](38.6,-77.6,39.1,-77.0);
      node["tourism"="motel"](38.6,-77.6,39.1,-77.0);
      node["amenity"="spa"](38.6,-77.6,39.1,-77.0);
      node["shop"="massage"](38.6,-77.6,39.1,-77.0);
      node["amenity"="bar"](38.6,-77.6,39.1,-77.0);
      node["amenity"="nightclub"](38.6,-77.6,39.1,-77.0);
    );
    out;
    """

    url = "https://overpass-api.de/api/interpreter"

    try:
        r = requests.post(url, data={"data": query}, timeout=30)
        data = r.json()
    except:
        return pd.DataFrame()

    rows = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})

        rows.append({
            "name": tags.get("name", "unknown"),
            "lat": el.get("lat"),
            "lng": el.get("lon"),
            "type": (
                tags.get("amenity")
                or tags.get("tourism")
                or tags.get("shop")
                or "unknown"
            )
        })

    return pd.DataFrame(rows)

df_raw = fetch_data()

# fallback if API fails
if df_raw.empty:
    st.warning("Using fallback dataset (API unavailable)")
    df_raw = pd.DataFrame({
        "name": [f"synthetic_{i}" for i in range(40)],
        "lat": LAT + np.random.uniform(-0.08, 0.08, 40),
        "lng": LNG + np.random.uniform(-0.08, 0.08, 40),
        "type": np.random.choice(["hotel","spa","bar","motel"], 40)
    })

# ================================
# 2. PROCESSING (cached)
# ================================
@st.cache_data
def process(df):
    def score(t):
        t = str(t).lower()
        if "hotel" in t or "motel" in t:
            return 2
        if "spa" in t or "massage" in t:
            return 3
        if "bar" in t or "nightclub" in t:
            return 1.5
        return 0

    df = df.copy()
    df["risk"] = df["type"].apply(score)

    if len(df) > 0:
        coords = df[["lat", "lng"]].to_numpy()

        db = DBSCAN(
            eps=0.6 / 6371,
            min_samples=2,
            metric="haversine"
        ).fit(np.radians(coords))

        df["cluster"] = db.labels_

    return df

df = process(df_raw)

# ================================
# 3. FILTER UI (does NOT trigger recompute)
# ================================
st.sidebar.header("Filters")

types = df["type"].unique().tolist()
selected = st.sidebar.multiselect("Types", types, default=types)
min_risk = st.sidebar.slider("Minimum Risk", 0.0, 5.0, 0.0)

filtered = df[(df["type"].isin(selected)) & (df["risk"] >= min_risk)]

st.write("Points:", len(filtered))

# ================================
# 4. MAP (cached to prevent flicker)
# ================================
@st.cache_data
def build_map(df):
    m = folium.Map(location=[LAT, LNG], zoom_start=11)

    if len(df) > 0:
        heat = [[r.lat, r.lng, r.risk] for r in df.itertuples()]
        HeatMap(heat, radius=18).add_to(m)

        for r in df.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=4,
                popup=f"{r.name} | {r.type} | {r.risk}",
                fill=True
            ).add_to(m)

    return m

m = build_map(filtered)

# ================================
# 5. RENDER
# ================================
st_folium(m, width=1200, height=700)
