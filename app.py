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
# 1. SIDEBAR: FILTERS & LEGEND
# ================================
st.sidebar.title("🔍 Intelligence Control")

if not poi_df.empty:
    all_types = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect(
        "Filter Business Categories", 
        options=all_types, 
        default=['motel', 'massage', 'spa', 'nightclub', 'hotel']
    )
    filtered_poi = poi_df[poi_df['type'].isin(selected_types)]
else:
    filtered_poi = pd.DataFrame()

st.sidebar.markdown("---")
st.sidebar.subheader("🗺️ Map Legend")
st.sidebar.markdown("""
<div style="background-color: #262730; padding: 15px; border-radius: 8px; border: 1px solid #464b5d;">
    <p style="margin: 0;">⚪ <b>White Dot:</b> Business</p>
    <hr style="margin: 12px 0; opacity: 0.3;">
    <p style="margin-bottom: 8px; font-weight: bold;">Vulnerability Level:</p>
    <div style="height: 18px; width: 100%; background: linear-gradient(to right, blue, cyan, lime, yellow, red); border-radius: 4px;"></div>
    <div style="display: flex; justify-content: space-between; font-size: 11px; margin-top: 6px; color: #afb0b6;">
        <span>Stable</span>
        <span>Critical</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ================================
# 2. THE GRID LOGIC (FIXES ZOOM)
# ================================
def get_grid_data(df):
    """Groups scores into a grid so the heatmap looks like blocks, not circles."""
    centers = {"Fairfax": [38.84, -77.30], "Loudoun": [39.01, -77.53], 
               "Arlington": [38.88, -77.10], "Alexandria": [38.80, -77.04]}
    
    grid_points = []
    for _, row in df.iterrows():
        base = centers.get("Fairfax")
        for county, coord in centers.items():
            if county in row['Name']:
                base = coord; break
        
        # Use Tract ID to create a unique but repeatable offset
        seed = int(row['tract'])
        np.random.seed(seed)
        lat = base[0] + np.random.uniform(-0.15, 0.15)
        lng = base[1] + np.random.uniform(-0.15, 0.15)
        
        # ROUNDING to the nearest 0.005 creates a "pixelated" grid effect
        # This prevents the individual rainbow circles at high zoom
        grid_lat = round(lat, 3)
        grid_lng = round(lng, 3)
        grid_points.append([grid_lat, grid_lng, row['vulnerability_score']])
    
    return grid_points

# ================================
# 3. MAIN DASHBOARD
# ================================
st.title("🛡️ NOVA Intelligence: Neighborhood Vulnerability")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodbpositron")

    if not census_df.empty:
        heat_data = get_grid_data(census_df)
        
        # KEY SETTINGS FOR ZOOM:
        # radius=50 and blur=30 makes the 'pixels' bleed together into a solid wash
        HeatMap(
            heat_data, 
            radius=45, 
            blur=25, 
            min_opacity=0.4,
            max_val=max([x[2] for x in heat_data]) if heat_data else 1.0,
            gradient={0.2: 'blue', 0.4: 'cyan', 0.6: 'lime', 0.8: 'yellow', 1.0: 'red'}
        ).add_to(m)

    if not filtered_poi.empty:
        # head(300) to keep zoom performance high
        for r in filtered_poi.head(300).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=4, color="black",
                weight=1, fill=True, fill_color="white", fill_opacity=0.9,
                popup=f"<b>{r.name}</b><br>{r.type}"
            ).add_to(m)

    st_folium(m, width=900, height=600, returned_objects=[])

with col2:
    st.metric("Total Points Scraped", f"{len(poi_df):,}")
    st.metric("Filtered Points", f"{len(filtered_poi):,}")
    st.markdown("---")
    st.subheader("⚠️ Critical Priority Alerts")
    top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
    for _, row in top_v.iterrows():
        st.error(f"**{row['Name']}**\nScore: {round(row['vulnerability_score'], 1)}")
