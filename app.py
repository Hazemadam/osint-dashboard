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
st.set_page_config(page_title="OSINT Intelligence Dashboard", layout="wide")

LAT = 38.85
LNG = -77.30

st.title("🗺️ OSINT Intelligence Dashboard")

# ================================
# SESSION STATE
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
            ["hotel", "motel", "bar", "nightclub", "cafe", "restaurant", "spa", "massage"], 40
        ),
        "city": "Simulated Region",
        "street": "Simulated Area",
        "source": "Synthetic Model",
        "osm_type": "synthetic",
        "osm_id": -1,
    })

# ================================
# FETCH DATA
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

    last_error = "No live response"

    for url in urls:
        for attempt in range(3):
            try:
                r = requests.post(
                    url,
                    data=query,
                    headers={"Content-Type": "text/plain"},
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

                    category = (
                        tags.get("amenity")
                        or tags.get("tourism")
                        or tags.get("shop")
                        or "unknown"
                    )

                    rows.append({
                        "name": tags.get("name") or "Unnamed Location",
                        "lat": lat,
                        "lng": lng,
                        "type": category,
                        "city": tags.get("addr:city") or "Unknown",
                        "street": tags.get("addr:street") or "Unknown",
                        "source": "OpenStreetMap",
                    })

                df = pd.DataFrame(rows)

                if not df.empty:
                    return df, f"Live data from {url}"

                last_error = f"{url} returned no data"

            except Exception as e:
                last_error = str(e)
                time.sleep(1.5)

    return pd.DataFrame(), last_error


# ================================
# LOAD DATA
# ================================
with st.spinner("Fetching OSINT data..."):
    df_raw, fetch_status = fetch_data()

if df_raw.empty:
    if st.session_state.last_live_data is not None:
        df_raw = st.session_state.last_live_data.copy()
        data_source = "Last live dataset"
    else:
        df_raw = st.session_state.fallback_data.copy()
        data_source = "Fallback dataset"
else:
    st.session_state.last_live_data = df_raw.copy()
    data_source = "Live OpenStreetMap"

st.sidebar.caption(f"Fetch status: {fetch_status}")
st.caption(f"Data source: {data_source}")


# ================================
# RISK MODEL (OSINT PATTERN-BASED)
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

    risk = CATEGORY_WEIGHTS.get(t, 0.3)

    # FIXED: correct boolean grouping
    nearby = df[
        ((df["lat"] - lat).abs() < 0.015)
        & ((df["lng"] - lng).abs() < 0.015)
    ]

    n = len(nearby)

    # density
    risk += min(n / 8, 3.0)

    types = set(nearby["type"].astype(str).str.lower())

    has_hotel = any(x in types for x in ["hotel", "motel"])
    has_night = any(x in types for x in ["bar", "nightclub"])
    has_spa = any(x in types for x in ["spa", "massage"])

    if has_hotel and has_night:
        risk += 2.5
    if has_hotel and has_spa:
        risk += 1.8
    if has_night and has_spa:
        risk += 1.2

    risk += min(sum(x in HIGH_RISK for x in types) * 0.4, 2.0)

    if n < 3:
        risk *= 0.7

    return float(risk)


# ================================
# PROCESS
# ================================
def process(df):
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

    return df


df = process(df_raw)


# ================================
# FILTERS
# ================================
types = sorted(df["type"].unique())

selected = st.sidebar.multiselect("Category", types, default=types)
min_risk = st.sidebar.slider("Minimum Risk", 0.0, 10.0, 0.0)

filtered = df[
    (df["type"].isin(selected))
    & (df["risk"] >= min_risk)
]

st.write("Points:", len(filtered))

st.dataframe(
    filtered[["name", "type", "topic", "risk", "city", "street"]],
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
        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=5,
            popup=f"{r.name} | {r.type} | Risk {r.risk:.2f}",
            fill=True,
            fill_opacity=0.7,
        ).add_to(m)

st_folium(m, width=1200, height=700)
