import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap
from sklearn.cluster import DBSCAN

# ================================
# 1. CONFIGURATION
# ================================
st.set_page_config(page_title="NOVA OSINT Intelligence", layout="wide")

# Center point for Northern Virginia (Fairfax/Centreville area)
LAT = 38.85
LNG = -77.30

st.title("🗺️ NOVA OSINT Intelligence Dashboard")
st.markdown("---")

# ================================
# 2. RISK WEIGHTS & CONSTANTS
# ================================
BASE_WEIGHTS = {
    "hotel": 2.0,
    "motel": 2.2,
    "bar": 1.5,
    "nightclub": 2.0,
    "restaurant": 0.8,
    "cafe": 0.6,
    "spa": 2.5,
    "massage": 2.8,
}

# ================================
# 3. DATA LOADING (GITHUB CLOUD)
# ================================
@st.cache_data(ttl=3600)
def load_intelligence_data():
    # UPDATED WITH YOUR REAL INFO
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    FILENAME = "nova_data.parquet" 
    
    # This is the direct link to the file your "Robot" just created
    URL = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/{FILENAME}"
    
    try:
        df = pd.read_parquet(URL)
        return df, "Live GitHub Cloud Storage"
    except Exception as e:
        st.error(f"Could not load cloud data: {e}")
        # This part stays as a backup
        dummy_data = pd.DataFrame({
            "name": ["Sample Point"], "lat": [LAT], "lng": [LNG],
            "type": ["cafe"], "city": ["NOVA"], "street": ["System"],
            "source": ["Fallback"],
        })
        return dummy_data, "Fallback Mode"

# ================================
# 4. RISK PROCESSING ENGINE
# ================================
def process_risk_model(df):
    df = df.copy()

    # Clustering (DBSCAN) - Groups points that are physically close
    if len(df) > 3:
        coords = df[["lat", "lng"]].to_numpy()
        db = DBSCAN(eps=0.01, min_samples=3).fit(coords)
        df["cluster"] = db.labels_
    else:
        df["cluster"] = -1

    risks = []

    for i, row in df.iterrows():
        lat, lng = row["lat"], row["lng"]
        category = str(row["type"]).lower()

        # Calculation 1: Base Weight
        base = BASE_WEIGHTS.get(category, 0.5)

        # Calculation 2: Local Density (Points within approx 1.5km)
        nearby = df[
            ((df["lat"] - lat).abs() < 0.015) &
            ((df["lng"] - lng).abs() < 0.015)
        ]
        density_score = min(len(nearby) / 10, 3)

        # Calculation 3: High-Risk Combinations (Synergy)
        types_nearby = set(nearby["type"].astype(str).str.lower())
        combo_score = 0
        if {"hotel", "motel"} & types_nearby and {"bar", "nightclub"} & types_nearby:
            combo_score += 2.0
        if {"hotel", "motel"} & types_nearby and {"spa", "massage"} & types_nearby:
            combo_score += 1.5

        # Calculation 4: Cluster Bonus
        cluster_bonus = 0
        if row["cluster"] != -1:
            cluster_size = (df["cluster"] == row["cluster"]).sum()
            cluster_bonus = min(cluster_size * 0.2, 2)

        # Final Score
        total_risk = base + density_score + combo_score + cluster_bonus
        risks.append(total_risk)

    df["risk"] = risks
    return df

processed_df = process_risk_model(df_raw)

# ================================
# 5. SIDEBAR FILTERS
# ================================
all_types = sorted(processed_df["type"].unique())
selected_categories = st.sidebar.multiselect("Filter Categories", all_types, default=all_types)
min_risk_threshold = st.sidebar.slider("Risk Severity Threshold", 0.0, 10.0, 2.0)

filtered_df = processed_df[
    (processed_df["type"].isin(selected_categories)) &
    (processed_df["risk"] >= min_risk_threshold)
]

# ================================
# 6. DASHBOARD VISUALS
# ================================
col1, col2 = st.columns([3, 1])

with col1:
    st.subheader("Intelligence Heatmap")
    m = folium.Map(location=[LAT, LNG], zoom_start=11, tiles="cartodbpositron")

    if not filtered_df.empty:
        # Create Heatmap Layer
        heat_data = [[r.lat, r.lng, r.risk] for r in filtered_df.itertuples()]
        HeatMap(heat_data, radius=15, blur=10).add_to(m)

        # Add Individual Markers
        for r in filtered_df.itertuples():
            # Color coding markers by risk
            color = "red" if r.risk > 5 else "orange" if r.risk > 3 else "blue"
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=6,
                popup=f"<b>{r.name}</b><br>Type: {r.type}<br>Risk Score: {round(r.risk, 2)}",
                color=color,
                fill=True,
                fill_opacity=0.7
            ).add_to(m)

    st_folium(m, width=1000, height=600)

with col2:
    st.subheader("High Risk Points")
    st.metric("Identified Points", len(filtered_df))
    
    # Display the top 10 riskiest locations
    top_risks = filtered_df.sort_values(by="risk", ascending=False).head(10)
    for i, row in top_risks.iterrows():
        st.write(f"⚠️ **{row['name']}**")
        st.caption(f"Score: {round(row['risk'], 2)} | {row['type']}")

# ================================
# 7. RAW DATA VIEW
# ================================
with st.expander("View Full Intelligence Table"):
    st.dataframe(filtered_df, use_container_width=True)
