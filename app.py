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
# STABLE MEMORY STORAGE
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
            ["hotel", "motel", "bar", "nightclub", "cafe", "restaurant", "spa", "shop"], 40
        ),
        "city": "Simulated Region",
        "street": "Simulated Area",
        "source": "Synthetic Model"
    })

# ================================
# DATA FETCH (ROBUST OVERPASS)
# ================================
@st.cache_data(ttl=600)
def fetch_data():
    query = """
    [out:json][timeout:25];
    (
      nwr["tourism"~"hotel|motel"](38.6,-77.6,39.1,-77.0);
      nwr["amenity"~"bar|nightclub|cafe|restaurant|spa"](38.6,-77.6,39.1,-77.0);
      nwr["shop"](38.6,-77.6,39.1,-77.0);
    );
    out center;
    """

    urls = [
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass-api.de/api/interpreter"
    ]

    for url in urls:
        for attempt in range(3):
            try:
                r = requests.post(
                    url,
                    data=query,
                    headers={"Content-Type": "text/plain"},
                    timeout=20
                )
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
                        "name": tags.get("name") or "Unnamed Location",
                        "lat": lat,
                        "lng": lng,
                        "type": tags.get("amenity") or tags.get("tourism") or tags.get("shop") or "unknown",
                        "city": tags.get("addr:city") or "Unknown",
                        "street": tags.get("addr:street") or "Unknown",
                        "source": "OpenStreetMap"
                    })

                if rows:
                    return pd.DataFrame(rows)

            except Exception:
                time.sleep(1.5)

    return pd.DataFrame()

# ================================
# LOAD DATA
# ================================
with st.spinner("Fetching live OSINT data..."):
    df_raw = fetch_data()

if df_raw.empty:
    st.warning("Using stable fallback dataset")

    df_raw = st.session_state.fallback_data

# Save last good live dataset
if not df_raw.empty:
    st.session_state.last_live_data = df_raw.copy()

# ================================
# PROCESSING
# ================================
@st.cache_data
def process(df):
    def score(t):
        t = str(t).lower()
        if "hotel" in t or "motel" in t:
            return 2.5
        if "spa" in t:
            return 3.5
        if "bar" in t or "nightclub" in t:
            return 1.8
        if "cafe" in t or "restaurant" in t:
            return 1.2
        return 0.5

    df = df.copy()
    df["risk"] = df["type"].apply(score)

    if len(df) < 2:
        df["cluster"] = -1
        return df

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
# FILTERS
# ================================
st.sidebar.header("Filters")

types = sorted(df["type"].astype(str).unique())

selected_types = st.sidebar.multiselect(
    "Category",
    options=types,
    default=types
)

min_risk = st.sidebar.slider("Minimum Risk Score", 0.0, 5.0, 0.0)

# ================================
# FILTER DATA
# ================================
filtered = df[
    (df["type"].isin(selected_types)) &
    (df["risk"] >= min_risk)
].copy()

st.write("📍 Points detected:", len(filtered))

# ================================
# DASHBOARD LAYOUT (MAP + TABLE)
# ================================
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("🗺️ Heatmap")

    m = folium.Map(location=[LAT, LNG], zoom_start=11)

    if len(filtered) > 0:
        heat = [[r.lat, r.lng, r.risk] for r in filtered.itertuples()]
        HeatMap(heat, radius=18).add_to(m)

        for r in filtered.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=5,
                popup=f"{r.name} | {r.type} | {r.risk}",
                fill=True,
                fill_opacity=0.8
            ).add_to(m)

    st_folium(m, width=900, height=650, key="osint_map")

with col2:
    st.subheader("📊 Intelligence Table")

    show_cols = ["name", "type", "risk", "city", "street", "cluster", "source"]

    st.dataframe(
        filtered[show_cols],
        use_container_width=True,
        height=650
    )
