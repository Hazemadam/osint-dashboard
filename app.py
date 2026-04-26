import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap

# ================================
# 1. CONFIGURATION & LOADING
# ================================
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
# 2. SIDEBAR: FILTERS & LEGEND
# ================================
st.sidebar.title("🔍 Intelligence Control")

# 1. Filter by Business Type
if not poi_df.empty:
    all_types = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect(
        "Filter Business Categories", 
        options=all_types, 
        default=['motel', 'massage', 'spa', 'nightclub', 'hotel']
    )
    # Apply Filter
    filtered_poi = poi_df[poi_df['type'].isin(selected_types)]
else:
    filtered_poi = pd.DataFrame()

st.sidebar.markdown("---")

# 2. THE KEY (LEGEND)
st.sidebar.subheader("🗺️ Map Legend")
st.sidebar.markdown("""
<div style="background-color: #262730; padding: 15px; border-radius: 8px; border: 1px solid #464b5d;">
    <p style="margin: 0;">⚪ <b>White Dot:</b> Targeted Business</p>
    <hr style="margin: 12px 0; opacity: 0.3;">
    <p style="margin-bottom: 8px; font-weight: bold;">Vulnerability Level:</p>
    <div style="height: 18px; width: 100%; background: linear-gradient(to right, blue, cyan, lime, yellow, red); border-radius: 4px;"></div>
    <div style="display: flex; justify-content: space-between; font-size: 11px; margin-top: 6px; color: #afb0b6;">
        <span>LOW (Stable)</span>
        <span>HIGH (Critical)</span>
    </div>
</div>
""", unsafe_allow_html=True)

st.sidebar.caption("Heatmap scales dynamically to prevent 'isolated circles' at high zoom levels.")

# ================================
# 3. COORDINATE LOGIC
# ================================
def get_coords_for_tract(row):
    centers = {
        "Fairfax": [38.8462, -77.3064],
        "Loudoun": [39.0100, -77.5300],
        "Arlington": [38.8816, -77.1000],
        "Alexandria": [38.8048, -77.0469]
    }
    base = centers["Fairfax"]
    for county, coord in centers.items():
        if county in row['Name']:
            base = coord
            break
    try:
        seed = int(row['tract'])
        np.random.seed(seed)
        lat_off = np.random.uniform(-0.12, 0.12) 
        lng_off = np.random.uniform(-0.12, 0.12)
        return [base[0] + lat_off, base[1] + lng_off]
    except:
        return base

# ================================
# 4. MAIN DASHBOARD
# ================================
st.title("🛡️ NOVA Intelligence: Neighborhood Vulnerability")

col1, col2 = st.columns([3, 1])

with col1:
    # Use CartoDB Positron for a clean, professional "intelligence" look
    m = folium.Map(location=[38.85, -77.30], zoom_start=10, tiles="cartodbpositron")

    if not census_df.empty:
        # Generate heat data with vulnerability score as the intensity weight
        heat_data = [[get_coords_for_tract(r)[0], get_coords_for_tract(r)[1], r['vulnerability_score']] for _, r in census_df.iterrows()]
        
        # SURGICAL FIX: max_zoom and min_opacity prevent the 'Vienna Circle' issue
        HeatMap(
            heat_data, 
            radius=35,       # Broad enough to cover neighborhoods
            blur=25,         # Smooths the transition between census tracts
            min_opacity=0.4, # Keeps the colors rich
            max_zoom=13,     # CRITICAL: Blends points into a solid wash when zooming in
            gradient={0.2: 'blue', 0.4: 'cyan', 0.6: 'lime', 0.8: 'yellow', 1.0: 'red'}
        ).add_to(m)

    if not filtered_poi.empty:
        # Render high-priority points
        # head(400) keeps the map fluid even on mobile/slower connections
        for r in filtered_poi.head(400).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], 
                radius=4, 
                color="black",
                weight=1, 
                fill=True, 
                fill_color="white", 
                fill_opacity=0.9,
                popup=f"<b>{r.name}</b><br>Type: {r.type}"
            ).add_to(m)

    st_folium(m, width=900, height=550, returned_objects=[])

with col2:
    st.metric("Total Intelligence Points", f"{len(poi_df):,}")
    st.metric("Filtered Points on Map", f"{len(filtered_poi):,}")
    st.markdown("---")
    st.subheader("⚠️ Critical Priority Alerts")
    
    # Sort by highest vulnerability first
    top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
    for _, row in top_v.iterrows():
        st.error(f"**{row['Name']}**\nScore: {round(row['vulnerability_score'], 1)}")

# Optional Raw Data Explorer
with st.expander("🔍 View Raw Intelligence Table"):
    st.dataframe(filtered_poi, use_container_width=True)
