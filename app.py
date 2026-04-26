import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap

# ================================
# 1. CONFIGURATION
# ================================
st.set_page_config(page_title="NOVA OSINT Intelligence V2", layout="wide")
LAT, LNG = 38.85, -77.30

st.title("🛡️ NOVA Vulnerability & Intelligence Dashboard")
st.markdown("---")

# ================================
# 2. DATA LOADING (TWO-STREAM)
# ================================
@st.cache_data(ttl=3600)
def load_all_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    
    # URL 1: Business Intelligence
    POI_URL = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet"
    # URL 2: Census Vulnerability
    CENSUS_URL = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet"
    
    try:
        poi_df = pd.read_parquet(POI_URL)
        census_df = pd.read_parquet(CENSUS_URL)
        return poi_df, census_df, "Live Cloud Data Sync"
    except Exception as e:
        st.error(f"Sync Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), "Offline"

poi_df, census_df, status = load_all_data()
st.sidebar.success(f"Status: {status}")

# ================================
# 3. ANALYSIS ENGINE
# ================================
def get_vulnerability_rating(row):
    score = row['vulnerability_score']
    if score > 7: return "Critical", "#d73027" # Dark Red
    if score > 4: return "Elevated", "#fc8d59" # Orange
    return "Stable", "#91cf60" # Green

# ================================
# 4. DASHBOARD LAYOUT
# ================================
col1, col2 = st.columns([3, 1])

with col1:
    st.subheader("Interactive Intelligence Overlay")
    st.caption("Circles = High-Risk Businesses | Heatmap = Census Vulnerability")
    
    # Initialize Map
    m = folium.Map(location=[LAT, LNG], zoom_start=10, tiles="cartodbpositron")

    # Layer 1: Census Vulnerability Heatmap (The "Environment")
    if not census_df.empty:
        # Note: In a full GIS app we'd use polygons, but a heatmap of tract scores 
        # is a great way to see "Vulnerability Clusters"
        heat_data = [[38.8, -77.2, s] for s in census_df['vulnerability_score']] # simplified for demo
        HeatMap(heat_data, radius=25, blur=20, min_opacity=0.3).add_to(m)

    # Layer 2: Business Points (The "Targets")
    if not poi_df.empty:
        for r in poi_df.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=5,
                popup=f"<b>{r.name}</b><br>Type: {r.type}",
                color="black",
                weight=1,
                fill=True,
                fill_color="red",
                fill_opacity=0.8
            ).add_to(m)

    st_folium(m, width=900, height=600)

with col2:
    st.subheader("Neighborhood Analysis")
    if not census_df.empty:
        avg_income = census_df['Median_Income'].mean()
        st.metric("Avg. Regional Income", f"${int(avg_income):,}")
        
        high_vuln_tracts = len(census_df[census_df['vulnerability_score'] > 6])
        st.metric("Critical Tracts Identified", high_vuln_tracts)
        
        st.markdown("### Top Priority Areas")
        # Showing neighborhoods with lowest income and highest risk business density
        top_census = census_df.sort_values('vulnerability_score', ascending=False).head(5)
        for _, row in top_census.iterrows():
            rating, color = get_vulnerability_rating(row)
            st.markdown(f"📍 **{row['Name']}**")
            st.caption(f"Status: {rating} | Score: {round(row['vulnerability_score'], 1)}")
    else:
        st.write("Census data loading...")

# ================================
# 5. DATA EXPLORER
# ================================
with st.expander("Explore Socio-Economic Raw Data"):
    st.dataframe(census_df, use_container_width=True)
