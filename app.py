import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium

# ================================
# 1. CONFIG & DATA LOADING
# ================================
st.set_page_config(page_title="NOVA Intelligence: Grid View", layout="wide")

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
# 2. SIDEBAR FILTERS & LEGEND
# ================================
st.sidebar.title("🔍 Grid Controls")

if not poi_df.empty:
    selected_types = st.sidebar.multiselect(
        "Business Types", 
        options=sorted(poi_df['type'].unique().tolist()), 
        default=['motel', 'massage', 'spa', 'nightclub']
    )
    filtered_poi = poi_df[poi_df['type'].isin(selected_types)]
else:
    filtered_poi = pd.DataFrame()

st.sidebar.markdown("---")
st.sidebar.subheader("📊 Vulnerability Key")
st.sidebar.markdown("""
<div style="background-color: #262730; padding: 10px; border-radius: 5px; border: 1px solid #464b5d;">
    <p><span style='color:#d73027;'>■</span> <b>Critical Risk</b> (Score 10+)</p>
    <p><span style='color:#fc8d59;'>■</span> <b>Elevated</b> (Score 6-9)</p>
    <p><span style='color:#fee08b;'>■</span> <b>Moderate</b> (Score 3-5)</p>
    <p><span style='color:#1a9850;'>■</span> <b>Stable</b> (Score 0-2)</p>
</div>
""", unsafe_allow_html=True)

# ================================
# 3. THE GRID GENERATOR
# ================================
def get_color(score):
    if score > 10: return '#d73027' # Red
    if score > 6:  return '#fc8d59' # Orange
    if score > 3:  return '#fee08b' # Yellow
    return '#1a9850' # Green

def create_grid(m, df):
    """Creates a grid of rectangles based on neighborhood coordinates."""
    centers = {
        "Fairfax": [38.8462, -77.3064],
        "Loudoun": [39.0100, -77.5300],
        "Arlington": [38.8816, -77.1000],
        "Alexandria": [38.8048, -77.0469]
    }
    
    # We create a 0.02 x 0.02 degree 'block' for each neighborhood
    size = 0.015 
    
    for _, row in df.iterrows():
        base = centers["Fairfax"]
        for region, coord in centers.items():
            if region in row['Name']:
                base = coord
                break
        
        # Determine the 'Box' location using Tract ID to scatter them
        try:
            tract_val = int(row['tract'])
            np.random.seed(tract_val)
            lat = base[0] + np.random.uniform(-0.1, 0.1)
            lng = base[1] + np.random.uniform(-0.15, 0.15)
            
            # Draw the square (Rectangle)
            color = get_color(row['vulnerability_score'])
            folium.Rectangle(
                bounds=[[lat, lng], [lat + size, lng + size]],
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.4,
                weight=1,
                popup=f"Tract: {row['Name']}<br>Score: {round(row['vulnerability_score'], 1)}"
            ).add_to(m)
        except:
            continue

# ================================
# 4. MAIN LAYOUT
# ================================
st.title("🛡️ NOVA Intelligence: Neighborhood Grid")

col1, col2 = st.columns([3, 1])

with col1:
    # Use a dark map to make the grid colors pop
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")

    if not census_df.empty:
        create_grid(m, census_df)

    if not filtered_poi.empty:
        for r in filtered_poi.head(300).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=3, color="white",
                weight=0.5, fill=True, fill_color="cyan", fill_opacity=1,
                popup=f"{r.name}"
            ).add_to(m)

    st_folium(m, width=900, height=600, returned_objects=[])

with col2:
    st.metric("Intelligence Points", f"{len(poi_df):,}")
    st.subheader("⚠️ Priority Sectors")
    top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
    for _, row in top_v.iterrows():
        st.error(f"**{row['Name']}**\nCritical Vulnerability")
