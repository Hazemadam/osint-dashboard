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
        # Load datasets
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        
        # --- AGGRESSIVE COLUMN REPAIR ---
        def standardize_coords(df):
            df.columns = [c.lower().strip() for c in df.columns]
            cols = df.columns
            
            # Find Latitude
            lat_col = next((c for c in cols if c in ['lat', 'latitude', 'y']), None)
            # Find Longitude
            lng_col = next((c for c in cols if c in ['lng', 'lon', 'long', 'longitude', 'x']), None)
            
            if not lat_col or not lng_col:
                raise ValueError(f"Could not find coordinates in columns: {list(cols)}")
                
            return df.rename(columns={lat_col: 'lat', lng_col: 'lng'})

        poi = standardize_coords(poi)
        census = standardize_coords(census)

        # --- SPATIAL CONVERSION (Safe Syntax) ---
        gdf_poi = gpd.GeoDataFrame(
            poi, 
            geometry=gpd.points_from_xy(poi['lng'], poi['lat']), 
            crs="EPSG:4326"
        )
        
        gdf_census = gpd.GeoDataFrame(
            census, 
            geometry=gpd.points_from_xy(census['lng'], census['lat']), 
            crs="EPSG:4326"
        )
        
        # Create 'Risk Bubbles' (Approx 1km)
        gdf_census.geometry = gdf_census.geometry.buffer(0.01) 
        
        return gdf_poi, gdf_census
    except Exception as e:
        st.error(f"Surgical Data Error: {e}")
        return gpd.GeoDataFrame(), gpd.GeoDataFrame()

poi_gdf, census_gdf = load_and_process_data()

# ================================
# 2. THE SPATIAL JOIN RISK ENGINE
# ================================
def apply_spatial_risk(poi_gdf, census_gdf):
    if poi_gdf.empty or census_gdf.empty:
        return poi_gdf

    # SPATIAL JOIN: Map neighborhood vulnerability to the specific business point
    # We use 'left' join to keep all businesses even if they fall outside a bubble
    joined = gpd.sjoin(poi_gdf, census_gdf[['vulnerability_score', 'geometry']], how='left', predicate='within')
    
    # Risk weights
    weights = {'stripclub': 12, 'massage': 10, 'nightclub': 9, 'motel': 8, 'spa': 5, 'bar': 4, 'hotel': 2}
    
    # Fill gaps for businesses outside bubbles with the dataset average
    mean_vulnerability = joined['vulnerability_score'].mean() if not joined['vulnerability_score'].isnull().all() else 0
    joined['vulnerability_score'] = joined['vulnerability_score'].fillna(mean_vulnerability)
    
    # Risk Score = Business Weight + (Localized Poverty * 8)
    joined['raw_score'] = joined.apply(lambda x: weights.get(str(x['type']).lower(), 1) + (x['vulnerability_score'] * 8), axis=1)
    
    # Calculate Standardized Thresholds for Color Spread
    avg = joined['raw_score'].mean()
    std = joined['raw_score'].std() if joined['raw_score'].std() > 0 else 1
    
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
    
    # Filter setup
    all_types = sorted(scored_gdf['type'].unique().tolist())
    requested_defaults = ['motel', 'massage', 'nightclub']
    safe_defaults = [t for t in requested_defaults if t in all_types]
    
    selected_types = st.sidebar.multiselect("Business Category", all_types, default=safe_defaults)
    selected_risks = st.sidebar.multiselect("Priority Level", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM', 'LOW'])
    
    final_df = scored_gdf[(scored_gdf['type'].isin(selected_types)) & (scored_gdf['level'].isin(selected_risks))]
    map_id = f"map_{hash(tuple(selected_types))}_{hash(tuple(selected_risks))}"
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
        for r in final_df.head(1000).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=6, color='white', weight=0.5,
                fill=True, fill_color=r.color, fill_opacity=1,
                popup=f"<b>{r.name}</b><br>Priority: {r.level}<br>Neighborhood Risk: {round(r.vulnerability_score, 2)}"
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
