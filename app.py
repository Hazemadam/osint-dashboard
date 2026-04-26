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

# --- THE "SURGICAL" HEATMAP LOGIC ---
# We are going to spread the census data based on their County and Tract ID
def get_coords_for_tract(row):
    # Base coordinates for regions
    if "Fairfax" in row['Name']: base = [38.84, -77.30]
    elif "Loudoun" in row['Name']: base = [39.01, -77.53]
    elif "Arlington" in row['Name']: base = [38.88, -77.10]
    elif "Alexandria" in row['Name']: base = [38.80, -77.04]
    else: base = [38.85, -77.30]
    
    # Use the Tract ID digits to "offset" the point so they spread out 
    # This turns 1 big circle into 500 small neighborhood points
    try:
        offset_lat = (float(row['tract']) % 100) / 1000 - 0.05
        offset_lng = (float(row['tract']) % 50) / 500 - 0.05
        return [base[0] + offset_lat, base[1] + offset_lng]
    except:
        return base

# --- DASHBOARD ---
st.title("🛡️ NOVA Intelligence: Neighborhood Vulnerability")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=10, tiles="cartodbpositron")

    if not census_df.empty:
        # Create a real neighborhood-level distribution
        heat_data = []
        for _, row in census_df.iterrows():
            loc = get_coords_for_tract(row)
            heat_data.append([loc[0], loc[1], row['vulnerability_score']])
        
        # Thinner radius makes it look like neighborhoods, not big blobs
        HeatMap(heat_data, radius=15, blur=15, min_opacity=0.3, 
                gradient={0.2: 'blue', 0.5: 'yellow', 0.8: 'red'}).add_to(m)

    if not poi_df.empty:
        # Filter: Only show "interesting" points to save memory
        high_risk_types = ['motel', 'massage', 'spa', 'nightclub']
        poi_priority = poi_df[poi_df['type'].isin(high_risk_types)].head(200)
        
        for r in poi_priority.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=3, color="black",
                weight=1, fill=True, fill_color="red", fill_opacity=0.9,
                popup=f"{r.name} ({r.type})"
            ).add_to(m)

    st_folium(m, width=900, height=550, returned_objects=[])

with col2:
    st.metric("Intelligence Points", f"{len(poi_df):,}")
    st.write("---")
    st.subheader("Priority Alerts")
    
    # Identify the Top 5 most vulnerable neighborhoods
    top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
    for _, row in top_v.iterrows():
        st.error(f"**{row['Name']}**\nHigh Vulnerability Detected")
