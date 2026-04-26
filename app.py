import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap

# ================================
# 1. CONFIG & MEMORY MANAGEMENT
# ================================
st.set_page_config(page_title="NOVA OSINT Lite", layout="wide")

@st.cache_data(ttl=3600, max_entries=10) # Limits cache memory
def load_all_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    POI_URL = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet"
    CENSUS_URL = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet"
    try:
        poi_df = pd.read_parquet(POI_URL)
        census_df = pd.read_parquet(CENSUS_URL)
        return poi_df, census_df
    except:
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_all_data()

# ================================
# 2. DATA PRUNING (To Save Memory)
# ================================
# Only keep the top 300 POIs by default to prevent crash
if len(poi_df) > 300:
    poi_display = poi_df.sample(300) 
else:
    poi_display = poi_df

# ================================
# 3. DASHBOARD
# ================================
st.title("🛡️ NOVA Intelligence (Optimized)")

col1, col2 = st.columns([3, 1])

with col1:
    # Use a simpler map tile to save memory
    m = folium.Map(location=[38.85, -77.30], zoom_start=10, tiles="CartoDB positron")

    # Efficient Census Mapping
    if not census_df.empty:
        # Pre-calculate coordinates for counties once
        coords = {"Fairfax": [38.84, -77.30], "Loudoun": [39.01, -77.53], "Arlington": [38.88, -77.10]}
        
        heat_data = []
        for _, row in census_df.iterrows():
            # Find which county this tract is in
            c_coord = [38.80, -77.04] # Default
            for name, loc in coords.items():
                if name in row['Name']:
                    c_coord = loc
                    break
            heat_data.append([c_coord[0], c_coord[1], row['vulnerability_score']])
        
        HeatMap(heat_data, radius=30, blur=20).add_to(m)

    # Efficient Point Mapping
    if not poi_display.empty:
        for r in poi_display.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=3,
                color="red",
                fill=True,
                popup=r.name
            ).add_to(m)

    st_folium(m, width=800, height=500, returned_objects=[]) # returned_objects=[] saves massive RAM

with col2:
    st.metric("Total Points Scraped", len(poi_df))
    st.write("Displaying 300 points to optimize performance.")
    
    if st.button("Reboot App Memory"):
        st.cache_data.clear()
        st.rerun()
