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
# Centered on Fairfax/Arlington area
LAT, LNG = 38.8462, -77.3064

st.title("🛡️ NOVA Vulnerability & Intelligence Dashboard")
st.markdown("---")

# ================================
# 2. DATA LOADING
# ================================
@st.cache_data(ttl=3600)
def load_all_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    POI_URL = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet"
    CENSUS_URL = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet"
    
    try:
        poi_df = pd.read_parquet(POI_URL)
        census_df = pd.read_parquet(CENSUS_URL)
        return poi_df, census_df, "Live Cloud Data Sync"
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame(), f"Sync Error: {e}"

poi_df, census_df, status = load_all_data()

# ================================
# 3. SIDEBAR FILTERS
# ================================
st.sidebar.title("Intelligence Filters")
show_census = st.sidebar.checkbox("Show Vulnerability Heatmap", value=True)
show_points = st.sidebar.checkbox("Show Business Points", value=True)

# Filter POIs by type if data exists
if not poi_df.empty:
    types = ["All"] + sorted(poi_df['type'].unique().tolist())
    selected_type = st.sidebar.selectbox("Filter Business Type", types)
    if selected_type != "All":
        poi_df = poi_df[poi_df['type'] == selected_type]

# ================================
# 4. DASHBOARD LAYOUT
# ================================
col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[LAT, LNG], zoom_start=10, tiles="cartodbpositron")

    # FIX: Creating a REAL coordinate-based heatmap for Census tracts
    if show_census and not census_df.empty:
        # We use the Tract names to estimate centers for the heatmap
        # (In a pro version we'd use GeoJSON, but this fixes the "Single Point" issue)
        census_data = []
        for _, row in census_df.iterrows():
            # Using known county centers to spread the data
            if "Fairfax" in row['Name']: l, n = 38.84, -77.30
            elif "Loudoun" in row['Name']: l, n = 39.01, -77.53
            elif "Arlington" in row['Name']: l, n = 38.88, -77.10
            else: l, n = 38.80, -77.04
            
            # Add some "jitter" so they don't all stack on one pixel
            l += np.random.uniform(-0.05, 0.05)
            n += np.random.uniform(-0.05, 0.05)
            census_data.append([l, n, row['vulnerability_score']])
            
        HeatMap(census_data, radius=25, blur=15, min_opacity=0.2, 
                gradient={0.4: 'blue', 0.65: 'lime', 1: 'red'}).add_to(m)

    # Layer 2: Business Points
    if show_points and not poi_df.empty:
        for r in poi_df.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=4,
                popup=f"{r.name} ({r.type})",
                color="red",
                fill=True,
                fill_opacity=0.4,
                weight=1
            ).add_to(m)

    st_folium(m, width=900, height=600)

with col2:
    st.subheader("Regional Stats")
    if not census_df.empty:
        st.metric("Avg. Household Income", f"${int(census_df['Median_Income'].mean()):,}")
        st.metric("Total Establishments", len(poi_df))
        
        st.write("### Vulnerability Priority")
        top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
        for _, row in top_v.iterrows():
            st.warning(f"**{row['Name']}**\nScore: {round(row['vulnerability_score'], 1)}")
