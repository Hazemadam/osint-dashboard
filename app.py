import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap
import os

# ================================
# CONFIG
# ================================
st.set_page_config(page_title="OSINT Dashboard", layout="wide")

LAT = 38.85
LNG = -77.30

st.title("🧠 OSINT Intelligence Dashboard (Stable Offline Mode)")


# ================================
# FAST LOCAL DATA (NO API CALLS)
# ================================
def generate_data():
    np.random.seed(42)
    return pd.DataFrame({
        "name": [f"Location {i}" for i in range(80)],
        "lat": LAT + np.random.uniform(-0.08, 0.08, 80),
        "lng": LNG + np.random.uniform(-0.08, 0.08, 80),
        "type": np.random.choice(
            ["hotel", "motel", "bar", "restaurant", "cafe", "spa", "nightclub"], 80
        ),
        "city": "Region",
        "street": "Unknown",
    })


df_raw = generate_data()
st.caption("Data source: local generated dataset (no API dependency)")


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


def risk(row, df):
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
# PROCESS
# ================================
df = df_raw.copy()
df["risk"] = df.apply(lambda r: risk(r, df), axis=1)


# ================================
# FILTERS
# ================================
st.sidebar.header("Filters")

types = sorted(df["type"].unique())

selected = st.sidebar.multiselect(
    "Category",
    types,
    default=types
)

min_risk = st.sidebar.slider("Min Risk", 0.0, 10.0, 0.0)

filtered = df[
    (df["type"].isin(selected)) &
    (df["risk"] >= min_risk)
]


# ================================
# METRICS
# ================================
c1, c2, c3 = st.columns(3)

c1.metric("Total", len(df))
c2.metric("Filtered", len(filtered))
c3.metric("Avg Risk", round(df["risk"].mean(), 2))


st.divider()


# ================================
# MAP + TABLE
# ================================
left, right = st.columns([1, 2])

with left:
    st.dataframe(
        filtered[["name", "type", "risk", "city", "street"]],
        use_container_width=True,
        height=600
    )

with right:
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
st.caption("Stable OSINT system — no live API dependency, no freezing, instant load")
