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

# --- SIDEBAR FILTERS & LEGEND ---
st.sidebar.title("🔍 Intelligence Control")

# 1. Filter by Business Type
if not poi_df.empty:
    all_types = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect(
        "Filter Business Categories", 
        options=all_types, 
        default=['motel', 'massage', 'spa', 'nightclub']
    )
    # Apply Filter
    filtered_poi = poi_df[poi_df['type'].isin(selected_types)]
else:
    filtered_poi = pd.DataFrame()

st.sidebar.markdown("---")

# 2. THE KEY (LEGEND)
st.sidebar.subheader("🗺️ Map Legend")
st.sidebar.info("● **White Markers**: Selected Businesses")
st.sidebar.markdown("""
<div style="line-height: 1.5;">
    <span style='color:red;'>■</span> <b>High Vulnerability</b> (Red Zone)<br>
    <span style='color:yellow;'>■</span> <b>Elevated Risk</b> (Yellow)<br>
    <span style='color:cyan;'>■</span> <b>Moderate</b> (Cyan)<br>
    <span style='color:blue;'>■</span> <b>Stable</b> (Blue)
</div>
""", unsafe_allow_html=True)

# --- COORDINATE DISTRIBUTOR ---
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

# --- DASHBOARD ---
st.title("🛡️ NOVA Intelligence: Neighborhood Vulnerability")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=10, tiles="cartodbpositron")

    if not census_df.empty:
        heat_data = [[get_coords_for_tract(r)[0], get_coords_for_tract(r)[1], r['vulnerability_score']] for _, r in census_df.iterrows()]
        HeatMap(heat_data, radius=25, blur=20, min_opacity=0.2, 
                gradient={0.2: 'blue', 0.4: 'cyan', 0.6: 'lime', 0.8: 'yellow', 1.0: 'red'}).add_to(m)

    if not filtered_poi.empty:
        # Display only up to 400 points to keep the map fast
        for r in filtered_poi.head(400).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=4, color="black",
                weight=1, fill=True, fill_color="white", fill_opacity=0.9,
                popup=f"<b>{r.name}</b><br>{r.type}"
            ).add_to(m)

    st_folium(m, width=900, height=550, returned_objects=[])

with col2:
    st.metric("Total Points Scraped", f"{len(poi_df):,}")
    st.metric("Points on Map", f"{len(filtered_poi):,}")
    st.markdown("---")
    st.subheader("⚠️ Top Vulnerable Tracts")
    top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
    for _, row in top_v.iterrows():
        st.error(f"**{row['Name']}**\nScore: {round(row['vulnerability_score'], 1)}")
