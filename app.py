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

# Keep a stable last-known-good dataset in memory
if "last_live_data" not in st.session_state:
    st.session_state.last_live_data = None

if "fallback_data" not in st.session_state:
    np.random.seed(42)
    st.session_state.fallback_data = pd.DataFrame({
        "name": [f"Simulated Location {i}" for i in range(40)],
        "lat": LAT + np.random.uniform(-0.08, 0.08, 40),
        "lng": LNG + np.random.uniform(-0.08, 0.08, 40),
        "type": np.random.choice(["hotel", "motel", "bar", "nightclub", "cafe", "restaurant", "spa", "massage"], 40),
        "city": "Simulated Region",
        "street": "Simulated Area",
        "source": "Synthetic Model",
        "osm_type": "synthetic",
        "osm_id": -1,
    })

# ================================
# HELPERS
# ================================
def topic_for(category: str) -> str:
    c = str(category).lower()
    if c in {"hotel", "motel"}:
        return "Lodging"
    if c in {"bar", "nightclub"}:
        return "Nightlife"
    if c in {"cafe", "restaurant"}:
        return "Food / Drink"
    if c in {"spa", "massage"}:
        return "Wellness"
    if c in {"shop"}:
        return "Retail"
    return "Other"

def score_for(category: str) -> float:
    c = str(category).lower()
    if c in {"hotel", "motel"}:
        return 2.5
    if c in {"spa", "massage"}:
        return 3.5
    if c in {"bar", "nightclub"}:
        return 1.8
    if c in {"cafe", "restaurant"}:
        return 1.2
    if c in {"shop"}:
        return 0.8
    return 0.5

# ================================
# 1. DATA FETCH (ROBUST + REPORTED)
# ================================
@st.cache_data(ttl=600)
def fetch_data():
    # Narrower, higher-signal query than "any amenity/tourism/shop"
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

    last_error = "No live response yet."

    for url in urls:
        for attempt in range(3):
            try:
                r = requests.post(
                    url,
                    data=query,
                    headers={
                        "Content-Type": "text/plain",
                        "User-Agent": "streamlit-osint-dashboard/1.0"
                    },
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json()

                rows = []
                for el in data.get("elements", []):
                    tags = el.get("tags", {})
                    lat = el.get("lat")
                    lng = el.get("lon")

                    if lat is None or lng is None:
                        center = el.get("center", {})
                        lat = center.get("lat")
                        lng = center.get("lon")

                    if lat is None or lng is None:
                        continue

                    category = tags.get("amenity") or tags.get("tourism") or tags.get("shop") or "unknown"

                    rows.append({
                        "name": tags.get("name") or "Unnamed Location",
                        "lat": lat,
                        "lng": lng,
                        "type": category,
                        "topic": topic_for(category),
                        "risk": score_for(category),
                        "city": tags.get("addr:city") or tags.get("is_in:city") or "Unknown",
                        "street": tags.get("addr:street") or "Unknown",
                        "source": "OpenStreetMap",
                        "osm_type": el.get("type", "unknown"),
                        "osm_id": el.get("id", -1),
                    })

                df = pd.DataFrame(rows)
                if not df.empty:
                    return df, f"Live data loaded from {url}"
                last_error = f"{url} returned 0 rows."
            except Exception as e:
                last_error = f"{url} attempt {attempt + 1} failed: {e}"
                time.sleep(1.5)

    return pd.DataFrame(), last_error

# ================================
# LOAD
# ================================
with st.spinner("Fetching live OSINT data..."):
    df_raw, fetch_status = fetch_data()

# Prefer last successful live data over synthetic fallback
data_source_label = "Live OpenStreetMap data"
if df_raw.empty:
    if st.session_state.last_live_data is not None and not st.session_state.last_live_data.empty:
        df_raw = st.session_state.last_live_data.copy()
        data_source_label = "Last successful live data"
    else:
        df_raw = st.session_state.fallback_data.copy()
        data_source_label = "Stable fallback dataset"

# Save live data when available
if not df_raw.empty and data_source_label == "Live OpenStreetMap data":
    st.session_state.last_live_data = df_raw.copy()

st.sidebar.header("Filters")
st.sidebar.caption(f"Fetch status: {fetch_status}")
st.caption(f"Data source: {data_source_label}")

# ================================
# 2. PROCESSING
# ================================
@st.cache_data
def process(df):
    df = df.copy()

    # Ensure required columns exist
    for col in ["name", "lat", "lng", "type", "topic", "risk", "city", "street", "source", "osm_type", "osm_id"]:
        if col not in df.columns:
            df[col] = "Unknown"

    if "risk" not in df.columns:
        df["risk"] = df["type"].apply(score_for)

    if "topic" not in df.columns:
        df["topic"] = df["type"].apply(topic_for)

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
# 3. FILTERS
# ================================
types = sorted(df["type"].dropna().astype(str).unique().tolist())

selected_types = st.sidebar.multiselect(
    "Category",
    options=types,
    default=types
)

min_risk = st.sidebar.slider("Minimum Risk Score", 0.0, 5.0, 0.0)

show_table = st.sidebar.checkbox("Show data table", value=True)

# ================================
# 4. FILTERED DATA
# ================================
filtered = df[
    (df["type"].astype(str).isin(selected_types)) &
    (df["risk"] >= min_risk)
].copy()

st.write("Points detected:", len(filtered))

if show_table and not filtered.empty:
    table_cols = ["name", "type", "topic", "risk", "city", "street", "cluster", "source"]
    st.dataframe(filtered[table_cols], use_container_width=True, hide_index=True)

# ================================
# 5. MAP
# ================================
m = folium.Map(location=[LAT, LNG], zoom_start=11)

if len(filtered) > 0:
    heat = [[r.lat, r.lng, float(r.risk)] for r in filtered.itertuples()]
    HeatMap(heat, radius=18).add_to(m)

    for r in filtered.itertuples():
        popup_html = f"""
        <b>{r.name}</b><br>
        Category: {r.type}<br>
        Topic: {r.topic}<br>
        Risk Score: {r.risk}<br>
        City: {r.city}<br>
        Street: {r.street}<br>
        Cluster: {r.cluster}<br>
        Source: {r.source}<br>
        OSM: {r.osm_type}/{r.osm_id}
        """

        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=5,
            popup=folium.Popup(popup_html, max_width=320),
            fill=True,
            fill_opacity=0.8
        ).add_to(m)

st_folium(m, width=1200, height=700, key="osint_map")
