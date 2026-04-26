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

# --- THE SURGICAL COORDINATE DISTRIBUTOR ---
def get_coords_for_tract(row):
    # Core Centers
    centers = {
        "Fairfax": [38.8462, -77.3064],
        "Loudoun": [39.0100, -77.5300],
        "Arlington": [38.8816, -77.1000],
        "Alexandria": [38.8048, -77.0469]
    }
    
    # Identify County
    base = centers["Fairfax"] # Default
    for county, coord in centers.items():
        if county in row['Name']:
            base = coord
            break
            
    # INCREASED OFFSET: This spreads the "heat" across the whole county area
    # instead of keeping it in one tight circle.
    try:
        seed = int(row['tract'])
        np.random.seed(seed) # Makes the spread consistent every time
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
        heat_data = []
        for _, row in census_df.iterrows():
            loc = get_coords_for_tract(row)
            # We add weight based on the vulnerability score
            heat_data.append([loc[0], loc[1], row['vulnerability_score']])
        
        # Professional Gradient: Blue (Safe) -> Lime -> Red (At Risk)
        HeatMap(heat_data, radius=25, blur=20, min_opacity=0.2, 
                gradient={0.2: 'blue', 0.4: 'cyan', 0.6: 'lime', 0.8: 'yellow', 1.0: 'red'}).add_to(m)

    if not poi_df.empty:
        # Focused Intelligence: High-risk business types only
        priority_types = ['motel', 'massage', 'spa', 'nightclub', 'hotel']
        poi_priority = poi_df[poi_df['type'].isin(priority_types)]
        
        for r in poi_priority.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=4, color="black",
                weight=1, fill=True, fill_color="white", fill_opacity=0.9,
                popup=f"<b>{r.name}</b><br>{r.type}"
            ).add_to(m)

    st_folium(m, width=900, height=550, returned_objects=[])

with col2:
    st.metric("Total Intelligence Points", f"{len(poi_df):,}")
    st.markdown("---")
    st.subheader("⚠️ Critical Priority Alerts")
    
    # Top 5 most vulnerable neighborhoods
    top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
    for _, row in top_v.iterrows():
        with st.container():
            st.error(f"**{row['Name']}**")
            st.caption(f"Vulnerability Score: {round(row['vulnerability_score'], 1)}")
