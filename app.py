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
        # Load census vulnerability
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        
        # --- COLUMN REPAIR LOGIC ---
        def repair_columns(df):
            # Convert all column names to lowercase for easier matching
            df.columns = [c.lower() for c in df.columns]
            # Rename variations of longitude/latitude
            rename_map = {
                'longitude': 'lng', 'lon': 'lng', 'long': 'lng',
                'latitude': 'lat'
            }
            return df.rename(columns=rename_map)

        poi = repair_columns(poi)
        census = repair_columns(census)

        # --- SPATIAL CONVERSION ---
        # Convert businesses to a GeoDataFrame (Points)
        gdf_poi = gpd.GeoDataFrame(
            poi, geometry=gpd.points_from_xy(poi.lng, poi.lat), crs="EPSG:4326"
        )
        
        # Convert census to a GeoDataFrame
        gdf_census = gpd.GeoDataFrame(
            census, geometry=gpd.points_from_xy(census.lng, census.lat), crs="EPSG:4326"
        )
        
        # Create 1km 'Neighborhood' zones around each census point
        # Using a small buffer for lat/long coordinates
        gdf_census.geometry = gdf_census.geometry.buffer(0.01) 
        
        return gdf_poi, gdf_census
    except Exception as e:
        st.error(f"Data Repair Error: {e}")
        return gpd.GeoDataFrame(), gpd.GeoDataFrame()

poi_gdf, census_gdf = load_and_process_data()

# ================================
# 2. THE SPATIAL JOIN RISK ENGINE
# ================================
def apply_spatial_risk(poi_gdf, census_gdf):
    if poi_gdf.empty or census_gdf.empty:
        return poi_gdf

    # --- THE SPATIAL JOIN ---
    # Links vulnerability_score to the business based on being 'within' the neighborhood buffer
    joined = gpd.sjoin(poi_gdf, census_gdf[['vulnerability_score', 'geometry']], how='left', predicate='within')
    
    # Business weights
    weights = {'stripclub': 12, 'massage': 10, 'nightclub': 9, 'motel': 8, 'spa': 5, 'bar': 4, 'hotel': 2}
    
    # Clean up and calculate risk
    joined['vulnerability_score'] = joined['vulnerability_score'].fillna(joined['vulnerability_score'].mean())
    joined['raw_score'] = joined.apply(lambda x: weights.get(str(x['type']).lower(), 1) + (x['vulnerability_score'] * 8), axis=1)
    
    # Standardized Balancing to ensure Red/Orange/Blue split
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
    scored_gdf = apply_spatial_risk(poi_gdf, census_gdf)
    
    all_types = sorted(scored_gdf['type'].unique().tolist())
    requested_defaults = ['motel', 'massage', 'nightclub']
    safe_defaults = [t for t in requested_defaults if t in all_types]
    
    selected_types = st.sidebar.multiselect("Business Category", all_types, default=safe_defaults)
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
                popup=f"<b>{r.name}</b><br>Risk: {r.level}<br>Score: {round(r.raw_score, 1)}"
            ).add_to(m)
            
    st_folium(m, width=900, height=650, key=map_id)

with col2:
    st.metric("Total Analyzed", len(poi_gdf))
    st.metric("Risk Detections", len(final_df))
    st.markdown("---")
    st.subheader("⚠️ High-Risk Localities")
    
    if not final_df.empty:
        high_hits = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(10)
        for _, row in high_hits.iterrows():
            st.error(f"**{row['name']}**\nPrecision Score: {round(row['raw_score'], 1)}")
