import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import numpy as np
import geopandas as gpd
from shapely.geometry import Point

# ================================
# 1. CONFIG & DATA LOADING
# ================================
st.set_page_config(page_title="NOVA Surgical Intelligence", layout="wide")

@st.cache_data(ttl=3600)
def load_and_process_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        # Load business locations
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        # Load census vulnerability (Must have lat/long or geometry to work)
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        
        # --- SPATIAL CONVERSION ---
        # Convert businesses to a GeoDataFrame (Points)
        gdf_poi = gpd.GeoDataFrame(
            poi, geometry=gpd.points_from_xy(poi.lng, poi.lat), crs="EPSG:4326"
        )
        
        # Convert census to a GeoDataFrame (Assuming census has geometry or center points)
        # If your census file only has center points, we create 'Buffer' circles to act as neighborhoods
        gdf_census = gpd.GeoDataFrame(
            census, geometry=gpd.points_from_xy(census.lng, census.lat), crs="EPSG:4326"
        )
        # Create 1km 'Neighborhood' zones around each census point
        gdf_census.geometry = gdf_census.geometry.buffer(0.01) # Approx 1km radius
        
        return gdf_poi, gdf_census
    except Exception as e:
        st.error(f"Spatial Error: {e}")
        return gpd.GeoDataFrame(), gpd.GeoDataFrame()

poi_gdf, census_gdf = load_and_process_data()

# ================================
# 2. THE SPATIAL JOIN RISK ENGINE
# ================================
def apply_spatial_risk(poi_gdf, census_gdf):
    if poi_gdf.empty or census_gdf.empty:
        return poi_gdf

    # --- THE SPATIAL JOIN ---
    # This 'joins' the poverty score to the business based on physical location
    joined = gpd.sjoin(poi_gdf, census_gdf[['vulnerability_score', 'geometry']], how='left', predicate='within')
    
    # Business weights
    weights = {'stripclub': 12, 'massage': 10, 'nightclub': 9, 'motel': 8, 'spa': 5, 'bar': 4, 'hotel': 2}
    
    # Calculate Risk
    joined['vulnerability_score'] = joined['vulnerability_score'].fillna(joined['vulnerability_score'].mean())
    joined['raw_score'] = joined.apply(lambda x: weights.get(x['type'].lower(), 1) + (x['vulnerability_score'] * 8), axis=1)
    
    # Standardized Balancing
    avg = joined['raw_score'].mean()
    std = joined['raw_score'].std()
    
    def get_color_label(s):
        if s > (avg + std): return 'red', 'HIGH'
        if s > avg: return 'orange', 'MEDIUM'
        return 'blue', 'LOW'
    
    joined['color'], joined['level'] = zip(*joined['raw_score'].apply(get_color_label))
    return joined

# ================================
# 3. SIDEBAR & FILTERS
# ================================
st.sidebar.title("🔍 Spatial OSINT Filter")

if not poi_gdf.empty:
    # Perform the Spatial Join
    scored_gdf = apply_spatial_risk(poi_gdf, census_gdf)
    
    # Filter Controls
    all_types = sorted(scored_gdf['type'].unique().tolist())
    selected_types = st.sidebar.multiselect("Business Category", all_types, default=['motel', 'massage', 'nightclub'])
    selected_risks = st.sidebar.multiselect("Priority Level", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM'])
    
    final_df = scored_gdf[(scored_gdf['type'].isin(selected_types)) & (scored_gdf['level'].isin(selected_risks))]
    map_id = f"map_{hash(tuple(selected_types))}"
else:
    final_df = pd.DataFrame()
    map_id = "empty"

# ================================
# 4. MAP & DASHBOARD
# ================================
st.title("🛡️ NOVA Surgical Risk: Spatial Join View")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    
    if not final_df.empty:
        for r in final_df.head(800).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=6, color='white', weight=0.5,
                fill=True, fill_color=r.color, fill_opacity=1,
                popup=f"<b>{r.name}</b><br>Neighborhood Risk: {round(r.vulnerability_score, 2)}"
            ).add_to(m)
            
    st_folium(m, width=900, height=650, key=map_id)

with col2:
    st.metric("Total Analyzed", len(poi_gdf))
    st.metric("Risk Detections", len(final_df))
    st.markdown("---")
    st.subheader("⚠️ High-Risk Localities")
    
    high_hits = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(10)
    for _, row in high_hits.iterrows():
        st.error(f"**{row['name']}**\nPrecision Score: {round(row['raw_score'], 1)}")
