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
st.set_page_config(page_title="OSINT Intelligence Dashboard", layout="wide")

LAT = 38.85
LNG = -77.30

st.title("🗺️ OSINT Intelligence Dashboard (Upgraded)")

# ================================
# 1. DATA FETCH (ROBUST + HIGH COVERAGE)
# ================================
@st.cache_data(ttl=600)
def fetch_data():
    query = """
    [out:json][timeout:25];
    (
      node(38.6,-77.6,39.1,-77.0)["amenity"];
      node(38.6,-77.6,39.1,-77.0)["tourism"];
      node(38.6,-77.6,39.1,-77.0)["shop"];
    );
    out center;
    """

    urls = [
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass-api.de/api/interpreter"
    ]

    for url in urls:
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

                rows.append({
                    "name": tags.get("name") or "Unnamed Location",
                    "lat": el.get("lat"),
                    "lng": el.get("lon"),
                    "type": tags.get("amenity") or tags.get("tourism") or tags.get("shop") or "unknown",
                    "city": tags.get("addr:city") or "Unknown",
                    "street": tags.get("addr:street") or "Unknown",
                    "source": "OpenStreetMap"
                })

            return pd.DataFrame(rows)

        except Exception:
            continue

    return pd.DataFrame()

# ================================
# LOADING
# ================================
with st.spinner("Loading OSINT data..."):
    df_raw = fetch_data()

# ================================
# 2. STABLE FALLBACK (NO RANDOM DRIFT)
# ================================
if df_raw.empty:
    st.warning("Using stable fallback dataset")

    if "fallback_data" not in st.session_state:
        np.random.seed(42)

        st.session_state.fallback_data = pd.DataFrame({
            "name": [f"Simulated Location {i}" for i in range(40)],
            "lat": LAT + np.random.uniform(-0.08, 0.08, 40),
            "lng": LNG + np.random.uniform(-0.08, 0.08, 40),
            "type": np.random.choice(["hotel","spa","bar","motel","cafe","shop"], 40),
            "city": "Simulated Region",
            "street": "Simulated Area",
            "source": "Synthetic Model"
        })

    df_raw = st.session_state.fallback_data

# ================================
# 3. PROCESSING (INTELLIGENCE LAYER)
# ================================
@st.cache_data
def process(df):
    def score(t):
        t = str(t).lower()
        if "hotel" in t or "motel" in t:
            return 2.5
        if "spa" in t or "massage" in t:
            return 3.5
        if "bar" in t or "nightclub" in t:
            return 1.8
        if "cafe" in t:
            return 1.2
        return 0.5

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
# 4. FILTERS
# ================================
st.sidebar.header("Filters")

types = sorted(df["type"].unique())

selected_types = st.sidebar.multiselect(
    "Category",
    options=types,
    default=types
)

min_risk = st.sidebar.slider("Minimum Risk Score", 0.0, 5.0, 0.0)

# ================================
# 5. FILTERED DATA
# ================================
filtered = df[
    (df["type"].isin(selected_types)) &
    (df["risk"] >= min_risk)
].copy()

st.write("📍 Points detected:", len(filtered))

# ================================
# 6. MAP (STABLE + ENRICHED)
# ================================
m = folium.Map(location=[LAT, LNG], zoom_start=11)

if len(filtered) > 0:
    heat = [[r.lat, r.lng, r.risk] for r in filtered.itertuples()]
    HeatMap(heat, radius=18).add_to(m)

    for r in filtered.itertuples():

        popup_html = f"""
        <b>{r.name}</b><br>
        Type: {r.type}<br>
        Risk Score: {r.risk}<br>
        City: {getattr(r, 'city', 'N/A')}<br>
        Street: {getattr(r, 'street', 'N/A')}<br>
        Cluster: {r.cluster}<br>
        Source: {getattr(r, 'source', 'Unknown')}
        """

        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=5,
            popup=folium.Popup(popup_html, max_width=300),
            fill=True
        ).add_to(m)

st_folium(m, width=1200, height=700, key="osint_map")
