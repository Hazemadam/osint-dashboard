import streamlit as st
import pandas as pd
import numpy as np
import requests
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap

# ================================
# CONFIG
# ================================
st.set_page_config(page_title="OSINT Dashboard", layout="wide")

LAT = 38.85
LNG = -77.30

st.title("🧠 OSINT Spatial Intelligence Dashboard")

# ================================
# FALLBACK DATA (ALWAYS WORKS)
# ================================
if "fallback_data" not in st.session_state:
    np.random.seed(42)
    st.session_state.fallback_data = pd.DataFrame({
        "name": [f"Simulated Site {i}" for i in range(50)],
        "lat": LAT + np.random.uniform(-0.08, 0.08, 50),
        "lng": LNG + np.random.uniform(-0.08, 0.08, 50),
        "type": np.random.choice(
            ["hotel", "motel", "bar", "restaurant", "cafe", "spa", "nightclub"], 50
        ),
        "city": "Simulated",
        "street": "Simulated",
    })

# ================================
# NON-BLOCKING FETCH (FAST FAIL)
# ================================
def fetch_data():
    query = """
    [out:json][timeout:10];
    (
      node["amenity"="bar"](38.6,-77.6,39.1,-77.0);
      node["amenity"="restaurant"](38.6,-77.6,39.1,-77.0);
      node["tourism"="hotel"](38.6,-77.6,39.1,-77.0);
      node["tourism"="motel"](38.6,-77.6,39.1,-77.0);
      node["amenity"="spa"](38.6,-77.6,39.1,-77.0);
    );
    out;
    """

    url = "https://overpass-api.de/api/interpreter"

    try:
        r = requests.post(
            url,
            data=query,
            headers={"Content-Type": "text/plain"},
            timeout=(3, 8)
        )

        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"

        data = r.json()
        elements = data.get("elements", [])

        if not elements:
            return None, "empty response"

        rows = []

        for el in elements:
            tags = el.get("tags", {})

            lat = el.get("lat")
            lng = el.get("lon")

            if lat is None or lng is None:
                continue

            rows.append({
                "name": tags.get("name", "Unnamed"),
                "lat": lat,
                "lng": lng,
                "type": (
                    tags.get("amenity")
                    or tags.get("tourism")
                    or "unknown"
                ),
                "city": tags.get("addr:city", "Unknown"),
                "street": tags.get("addr:street", "Unknown"),
            })

        return pd.DataFrame(rows), "live"

    except Exception as e:
        return None, str(e)


# ================================
# LOAD DATA (INSTANT UI FIRST)
# ================================
placeholder = st.empty()
placeholder.info("Loading OSINT dataset...")

df_raw, status = fetch_data()

if df_raw is None or df_raw.empty:
    df_raw = st.session_state.fallback_data.copy()
    source = "Fallback dataset (live failed)"
else:
    source = "Live OpenStreetMap"

placeholder.success(f"Data ready: {source} | {status}")


# ================================
# RISK MODEL
# ================================
CATEGORY = {
    "hotel": 2.0,
    "motel": 2.2,
    "bar": 1.3,
    "nightclub": 1.8,
    "restaurant": 0.8,
    "cafe": 0.6,
    "spa": 2.4,
}

def compute_risk(row, df):
    t = str(row["type"]).lower()

    base = CATEGORY.get(t, 0.3)

    nearby = df[
        ((df["lat"] - row["lat"]).abs() < 0.015) &
        ((df["lng"] - row["lng"]).abs() < 0.015)
    ]

    density = min(len(nearby) / 8, 3)

    types = set(nearby["type"].astype(str).str.lower())

    bonus = 0
    if {"hotel", "motel"} & types and {"bar", "nightclub"} & types:
        bonus += 2.0

    return float(base + density + bonus)


# ================================
# PROCESS
# ================================
df = df_raw.copy()
df["type"] = df["type"].astype(str).str.lower()
df["risk"] = df.apply(lambda r: compute_risk(r, df), axis=1)


# ================================
# FILTER UI
# ================================
st.sidebar.header("Filters")

types = sorted(df["type"].unique())

selected = st.sidebar.multiselect(
    "Category",
    types,
    default=types
)

min_risk = st.sidebar.slider("Minimum Risk", 0.0, 10.0, 0.0)


filtered = df[
    (df["type"].isin(selected)) &
    (df["risk"] >= min_risk)
]


# ================================
# METRICS
# ================================
col1, col2, col3 = st.columns(3)

col1.metric("Total Points", len(df))
col2.metric("Filtered", len(filtered))
col3.metric("Avg Risk", round(df["risk"].mean(), 2))


st.divider()


# ================================
# TABLE + MAP
# ================================
left, right = st.columns([1, 2])

with left:
    st.subheader("Data Table")
    st.dataframe(
        filtered[["name", "type", "risk", "city", "street"]],
        use_container_width=True,
        height=600
    )

with right:
    st.subheader("Map View")

    m = folium.Map(location=[LAT, LNG], zoom_start=11)

    if not filtered.empty:
        HeatMap(
            [[r.lat, r.lng, r.risk] for r in filtered.itertuples()],
            radius=18
        ).add_to(m)

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
# FOOTER
# ================================
st.caption("OSINT system: OpenStreetMap + spatial clustering + risk scoring + fallback resilience")
