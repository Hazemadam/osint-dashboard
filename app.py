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

st.title("🗺️ OSINT Hotspot Dashboard (Fully Stable)")

# ================================
# 1. DATA (cached)
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

    url = "https://overpass.kumi.systems/api/interpreter"

    try:
        r = requests.post(
            url,
            data=query,
            headers={"Content-Type": "text/plain"},
            timeout=30
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        st.warning(f"Overpass issue: {e}")
        return pd.DataFrame()

    rows = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})

        rows.append({
            "name": tags.get("name", "unknown"),
            "lat": el.get("lat"),
            "lng": el.get("lon"),
            "type": tags.get("amenity") or tags.get("tourism") or tags.get("shop") or "unknown"
        })

    return pd.DataFrame(rows)

df_raw = fetch_data()

# ================================
# 2. STABLE FALLBACK (CRITICAL FIX)
# ================================
if df_raw.empty:
    st.warning("Using fallback dataset")

    if "fallback_data" not in st.session_state:
        st.session_state.fallback_data = pd.DataFrame({
            "name": [f"synthetic_{i}" for i in range(40)],
            "lat": LAT + np.random.uniform(-0.08, 0.08, 40),
            "lng": LNG + np.random.uniform(-0.08, 0.08, 40),
            "type": np.random.choice(["hotel","spa","bar","motel"], 40)
        })

    df_raw = st.session_state.fallback_data

# ================================
# 3. PROCESSING
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

    if len(df) < 2:
        df["cluster"] = -1
        return df

    coords = df[["lat","lng"]].to_numpy()

    db = DBSCAN(
        eps=0.6/6371,
        min_samples=2,
        metric="haversine"
    ).fit(np.radians(coords))

    df["cluster"] = db.labels_
    return df

df = process(df_raw)

# ================================
# 4. UI
# ================================
st.sidebar.header("Filters")

types = sorted(df["type"].unique())

selected_types = st.sidebar.multiselect(
    "Types",
    options=types,
    default=types
)

min_risk = st.sidebar.slider("Minimum Risk", 0.0, 5.0, 0.0)

# ================================
# 5. FILTER
# ================================
filtered = df[
    (df["type"].isin(selected_types)) &
    (df["risk"] >= min_risk)
].copy()

st.write("Points:", len(filtered))

# ================================
# 6. MAP (STABLE)
# ================================
m = folium.Map(location=[LAT, LNG], zoom_start=11)

if len(filtered) > 0:
    heat = [[r.lat, r.lng, r.risk] for r in filtered.itertuples()]
    HeatMap(heat, radius=18).add_to(m)

    for r in filtered.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=4,
            popup=f"{r.name} | {r.type} | {r.risk}",
            fill=True
        ).add_to(m)

st_folium(m, width=1200, height=700, key="osint_map")
