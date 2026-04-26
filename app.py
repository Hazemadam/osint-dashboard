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
# SIDEBAR
# ================================
st.sidebar.title("🔍 Intelligence Control")

if not poi_df.empty:
    all_types = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect(
        "Filter Business Categories", 
        options=all_types, 
        default=['motel', 'massage', 'spa', 'nightclub']
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
    <div style="height: 18px; width: 100%; background: linear-gradient(to right, blue, cyan, lime, yellow, red); border-radius: 4px;"></div>
    <div style="display: flex; justify-content: space-between; font-size: 11px; margin-top: 6px;">
        <span>Stable</span>
        <span>Critical</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ================================
# COORDINATE SPREAD (FIXED)
# ================================
def get_calibrated_heat_data(df):
    centers = {"Fairfax": [38.84, -77.30], "Loudoun": [39.01, -77.53], 
               "Arlington": [38.88, -77.10], "Alexandria": [38.80, -77.04]}
    
    heat_points = []
    for _, row in df.iterrows():
        base = centers.get("Fairfax")
        for county, coord in centers.items():
            if county in row['Name']:
                base = coord; break
        
        # Use a much smaller jitter (0.08) to keep heat within county lines
        seed = int(row['tract'])
        np.random.seed(seed)
        lat = base[0] + np.random.uniform(-0.08, 0.08)
        lng = base[1] + np.random.uniform(-0.08, 0.08)
        
        heat_points.append([lat, lng, row['vulnerability_score']])
    return heat_points

# ================================
# MAIN DASHBOARD
# ================================
st.title("🛡️ NOVA Intelligence: Neighborhood Vulnerability")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodbpositron")

    if not census_df.empty:
        heat_data = get_calibrated_heat_data(census_df)
        
        # THE FIX: Lower radius (18) + High Blur (20) 
        # This keeps the 'red' only in the truly high-score areas.
        HeatMap(
            heat_data, 
            radius=18, 
            blur=20, 
            min_opacity=0.3,
            max_zoom=18, # Allows you to zoom all the way in without circles breaking
            gradient={0.4: 'blue', 0.6: 'lime', 0.8: 'yellow', 1.0: 'red'}
        ).add_to(m)

    if not filtered_poi.empty:
        # Prioritize quality over quantity for the map markers
        for r in filtered_poi.head(250).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=4, color="black",
                weight=1, fill=True, fill_color="white", fill_opacity=0.9,
                popup=f"<b>{r.name}</b><br>{r.type}"
            ).add_to(m)

    st_folium(m, width=900, height=600, returned_objects=[])

with col2:
    st.metric("Intelligence Points", f"{len(poi_df):,}")
    st.subheader("⚠️ Priority Alerts")
    top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
    for _, row in top_v.iterrows():
        st.error(f"**{row['Name']}**\nScore: {round(row['vulnerability_score'], 1)}")
