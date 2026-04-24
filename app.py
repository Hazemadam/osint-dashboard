import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap
import os
import requests

# ================================
# CONFIG
# ================================
st.set_page_config(page_title="OSINT Intelligence Platform", layout="wide")

LAT = 38.85
LNG = -77.30

st.title("🧠 OSINT Intelligence Platform (Stable Mode)")

DATA_FILE = "osm_cache.csv"


# ================================
# OFFLINE-FIRST DATA LOADING
# ================================
def generate_fallback():
    np.random.seed(42)
    return pd.DataFrame({
        "name": [f"Simulated Site {i}" for i in range(60)],
        "lat": LAT + np.random.uniform(-0.08, 0.08, 60),
        "lng": LNG + np.random.uniform(-0.08, 0.08, 60),
        "type": np.random.choice(
            ["hotel", "motel", "bar", "restaurant", "cafe", "spa", "nightclub"], 60
        ),
        "city": "Simulated",
        "street": "Simulated",
    })


def load_data():
    # 1. Use cached dataset if exists
    if os.path.exists(DATA_FILE):
        try:
            df = pd.read_csv(DATA_FILE)
            if len(df) > 0:
                return df, "cached dataset"
        except:
            pass

    # 2. fallback if no cache
    return generate_fallback(), "synthetic fallback"


def save_cache(df):
    df.to_csv(DATA_FILE, index=False)


df_raw, source = load_data()
st.caption(f"Data source: {source}")


# ================================
# RISK ENGINE (STABLE MODEL)
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

    density = min(len(nearby) / 10, 3)

    types = set(nearby["type"].astype(str).str.lower())

    combo = 0
    if {"hotel", "motel"} & types and {"bar", "nightclub"} & types:
        combo += 2.0

    return float(base + density + combo)


# ================================
# PROCESS DATA
# ================================
df = df_raw.copy()
df["type"] = df["type"].astype(str).str.lower()
df["risk"] = df.apply(lambda r: compute_risk(r, df), axis=1)


# ================================
# SIDEBAR FILTERS
# ================================
st.sidebar.header("Filters")

types = sorted(df["type"].unique())

selected_types = st.sidebar.multiselect(
    "Category",
    types,
    default=types
)

min_risk = st.sidebar.slider("Minimum Risk", 0.0, 10.0, 0.0)

filtered = df[
    (df["type"].isin(selected_types)) &
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
# MAP + TABLE
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
    st.subheader("Risk Map")

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
# OPTIONAL: DATA REFRESH BUTTON
# ================================
st.divider()

if st.button("🔄 Regenerate Dataset (Simulated Refresh)"):
    df_new = generate_fallback()
    save_cache(df_new)
    st.success("Dataset refreshed (saved to cache). Reload page to apply.")
