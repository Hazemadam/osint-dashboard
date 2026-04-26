import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap

st.set_page_config(page_title="NOVA Intelligence Pro", layout="wide")

@st.cache_data(ttl=3600)
def load_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        return poi, census
    except:
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# ================================
# 1. THE GRID SPREADER (FIXES BLOB)
# ================================
def get_neighborhood_grid(df):
    # Precise centers for NOVA sub-regions
    centers = {
        "Fairfax": [38.8462, -77.3064],
        "Loudoun": [39.0100, -77.5300],
        "Arlington": [38.8816, -77.1000],
        "Alexandria": [38.8048, -77.0469]
    }
    
    points = []
    for _, row in df.iterrows():
        # 1. Identify which region center to start from
        base = centers["Fairfax"]
        for region, coord in centers.items():
            if region in row['Name']:
                base = coord
                break
        
        # 2. Use the Tract ID to create a unique, repeatable "Neighborhood" offset
        # This prevents all tracts from stacking in one central blob
        try:
            tract_val = int(row['tract'])
            np.random.seed(tract_val) # Keeps neighborhoods consistent
            # We scatter the points in a 0.1 degree radius around the center
            lat = base[0] + np.random.uniform(-0.08, 0.08)
            lng = base[1] + np.random.uniform(-0.12, 0.12)
            points.append([lat, lng, row['vulnerability_score']])
        except:
            continue
    return points

# ================================
# 2. DASHBOARD & FILTERS
# ================================
st.sidebar.title("🔍 Intelligence Control")
if not poi_df.empty:
    selected_types = st.sidebar.multiselect(
        "Filter Business Type", 
        options=sorted(poi_df['type'].unique().tolist()), 
        default=['motel', 'massage', 'spa', 'nightclub']
    )
    filtered_poi = poi_df[poi_df['type'].isin(selected_types)]
else:
    filtered_poi = pd.DataFrame()

# ================================
# 3. MAP GENERATION
# ================================
st.title("🛡️ NOVA Intelligence: Neighborhood Vulnerability")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodbpositron")

    if not census_df.empty:
        heat_data = get_neighborhood_grid(census_df)
        
        # CRITICAL SETTINGS: 
        # radius=20 and blur=15 ensures the heat stays in neighborhood "cells"
        HeatMap(
            heat_data, 
            radius=20, 
            blur=15, 
            min_opacity=0.3,
            gradient={0.4: 'blue', 0.6: 'cyan', 0.8: 'yellow', 1.0: 'red'}
        ).add_to(m)

    if not filtered_poi.empty:
        # Show specific targets as white markers
        for r in filtered_poi.head(200).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=4, color="black",
                weight=1, fill=True, fill_color="white", fill_opacity=0.9,
                popup=f"<b>{r.name}</b><br>{r.type}"
            ).add_to(m)

    st_folium(m, width=900, height=600, returned_objects=[])

with col2:
    st.metric("Intelligence Points", f"{len(poi_df):,}")
    st.markdown("---")
    st.subheader("⚠️ Priority Hotspots")
    top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
    for _, row in top_v.iterrows():
        st.error(f"**{row['Name']}**\nCritical Vulnerability")
