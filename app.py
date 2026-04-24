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

# Keep last known good dataset
if "last_live_data" not in st.session_state:
    st.session_state.last_live_data = None

# fallback dataset
if "fallback_data" not in st.session_state:
    np.random.seed(42)
    st.session_state.fallback_data = pd.DataFrame({
        "name": [f"Simulated Location {i}" for i in range(40)],
        "lat": LAT + np.random.uniform(-0.08, 0.08, 40),
        "lng": LNG + np.random.uniform(-0.08, 0.08, 40),
        "type": np.random.choice(
            ["hotel", "motel", "bar", "nightclub", "cafe", "restaurant", "spa", "massage"], 40
        ),
        "city": "Simulated Region",
        "street": "Simulated Area",
        "source": "Synthetic Model",
        "osm_type": "synthetic",
        "osm_id": -1,
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
                    lat = el.get("lat") or el.get("center", {}).get("lat")
                    lng = el.get("lon") or el.get("center", {}).get("lon")

                    if lat is None or lng is None:
                        continue

                    category = tags.get("amenity") or tags.get("tourism") or tags.get("shop") or "unknown"

                    rows.append({
                        "name": tags.get("name") or "Unnamed Location",
                        "lat": lat,
                        "lng": lng,
                        "type": category,
                        "city": tags.get("addr:city") or "Unknown",
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
# LOAD DATA
# ================================
with st.spinner("Fetching live OSINT data..."):
    df_raw, fetch_status = fetch_data()

if df_raw.empty:
    if st.session_state.last_live_data is not None:
        df_raw = st.session_state.last_live_data.copy()
        data_source_label = "Last successful live data"
    else:
        df_raw = st.session_state.fallback_data.copy()
        data_source_label = "Stable fallback dataset"
else:
    st.session_state.last_live_data = df_raw.copy()
    data_source_label = "Live OpenStreetMap data"

st.sidebar.header("Filters")
st.sidebar.caption(f"Fetch status: {fetch_status}")
st.caption(f"Data source: {data_source_label}")


# ================================
# RISK ENGINE (NEW OSINT MODEL)
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

HIGH_RISK_GROUPS = {"hotel", "motel", "nightclub", "bar", "spa", "massage"}


def compute_risk(row, df):
    lat, lng = row["lat"], row["lng"]
    category = str(row["type"]).lower()

    risk = CATEGORY_WEIGHTS.get(category, 0.3)

    # local neighborhood window
   nearby = df[
    ((df["lat"] - lat).abs() < 0.015)
    & ((df["lng"] - lng).abs() < 0.015)
]

    n_neighbors = len(nearby)

    # density signal
    risk += min(n_neighbors / 8, 3.0)

    nearby_types = set(nearby["type"].astype(str).str.lower())

    has_hotel = any(t in nearby_types for t in ["hotel", "motel"])
    has_nightlife = any(t in nearby_types for t in ["bar", "nightclub"])
    has_spa = any(t in nearby_types for t in ["spa", "massage"])

    # co-location patterns
    if has_hotel and has_nightlife:
        risk += 2.5
    if has_hotel and has_spa:
        risk += 1.8
    if has_nightlife and has_spa:
        risk += 1.2

    # cluster amplification
    high_risk_count = sum(t in HIGH_RISK_GROUPS for t in nearby_types)
    risk += min(high_risk_count * 0.4, 2.0)

    # isolation penalty
    if n_neighbors < 3:
        risk *= 0.7

    return float(risk)


# ================================
# PROCESS DATA
# ================================
@st.cache_data
def process(df):
    df = df.copy()
    df["type"] = df["type"].astype(str).str.lower()

    df["risk"] = def process(df):
    df = df.copy()
    df["type"] = df["type"].astype(str).str.lower()

    risks = []
    for _, row in df.iterrows():
        risks.append(compute_risk(row, df))

    df["risk"] = risks

    def topic(t):
        if t in {"hotel", "motel"}:
            return "Lodging"
        if t in {"bar", "nightclub"}:
            return "Nightlife"
        if t in {"spa", "massage"}:
            return "Wellness"
        if t in {"restaurant", "cafe"}:
            return "Food"
        return "Other"

    df["topic"] = df["type"].apply(topic)
    df["cluster"] = -1

    return df

    def topic(t):
        if t in {"hotel", "motel"}:
            return "Lodging"
        if t in {"bar", "nightclub"}:
            return "Nightlife"
        if t in {"spa", "massage"}:
            return "Wellness"
        if t in {"restaurant", "cafe"}:
            return "Food"
        return "Other"

    df["topic"] = df["type"].apply(topic)
    df["cluster"] = -1

    return df


df = process(df_raw)


# ================================
# FILTERS
# ================================
types = sorted(df["type"].dropna().unique().tolist())

selected_types = st.sidebar.multiselect(
    "Category",
    options=types,
    default=types
)

min_risk = st.sidebar.slider("Minimum Risk Score", 0.0, 10.0, 0.0)

show_table = st.sidebar.checkbox("Show data table", value=True)


filtered = df[
    (df["type"].isin(selected_types)) &
    (df["risk"] >= min_risk)
].copy()

st.write("Points detected:", len(filtered))

if show_table and not filtered.empty:
    st.dataframe(
        filtered[["name", "type", "topic", "risk", "city", "street", "source"]],
        use_container_width=True,
        hide_index=True
    )


# ================================
# MAP
# ================================
m = folium.Map(location=[LAT, LNG], zoom_start=11)

if not filtered.empty:
    heat = [[r.lat, r.lng, r.risk] for r in filtered.itertuples()]
    HeatMap(heat, radius=18).add_to(m)

    for r in filtered.itertuples():
        popup = f"""
        <b>{r.name}</b><br>
        Type: {r.type}<br>
        Topic: {r.topic}<br>
        Risk: {r.risk:.2f}<br>
        City: {r.city}<br>
        Street: {r.street}<br>
        Source: {r.source}
        """

        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=5,
            popup=folium.Popup(popup, max_width=300),
            fill=True,
            fill_opacity=0.8
        ).add_to(m)

st_folium(m, width=1200, height=700, key="osint_map")
