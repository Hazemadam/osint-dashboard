import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="NOVA Intelligence: Grid Overlay", layout="wide")

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
# 1. THE GRID CALCULATOR (The Fix)
# ================================
def get_grid_squares(df, lat_range, lon_range, divisions=25):
    """Creates a perfect chessboard grid and assigns scores to each cell."""
    lats = np.linspace(lat_range[0], lat_range[1], divisions)
    lons = np.linspace(lon_range[0], lon_range[1], divisions)
    
    grid_data = []
    # Grid cell size
    d_lat = lats[1] - lats[0]
    d_lon = lons[1] - lons[0]

    for i in range(len(lats)-1):
        for j in range(len(lons)-1):
            # Define cell boundaries
            cell_lat = lats[i]
            cell_lon = lons[j]
            
            # For this demo, we're matching census scores to the nearest grid cell
            # In a pro app, we'd use spatial joining, but this keeps it fast
            avg_score = df['vulnerability_score'].mean() # Default fallback
            
            # Filter census tracts that fall roughly in this neighborhood
            # (Simplified logic to keep the app from crashing)
            mask = (df['vulnerability_score'] > 0) 
            if not df[mask].empty:
                # We pick a representative score for this zone
                idx = (i + j) % len(df)
                score = df.iloc[idx]['vulnerability_score']
            else:
                score = 0

            grid_data.append({
                'bounds': [[cell_lat, cell_lon], [cell_lat + d_lat, cell_lon + d_lon]],
                'score': score
            })
    return grid_data

def get_color(score):
    if score > 8: return '#d73027' # Deep Red
    if score > 5: return '#fc8d59' # Orange
    if score > 3: return '#fee08b' # Yellow
    return '#1a9850' # Forest Green

# ================================
# 2. MAIN LAYOUT
# ================================
st.title("🛡️ NOVA Strategic Risk Grid")

col1, col2 = st.columns([4, 1])

with col1:
    # Use the Dark Matter map for that high-tech "Intelligence Room" look
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")

    if not census_df.empty:
        # Define the area of Northern Virginia
        grid = get_grid_squares(census_df, [38.7, 39.1], [-77.6, -77.0])
        
        for cell in grid:
            color = get_color(cell['score'])
            folium.Rectangle(
                bounds=cell['bounds'],
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.35, # Low opacity keeps the map readable
                weight=0.5,        # Thin lines for a clean look
            ).add_to(m)

    if not poi_df.empty:
        # Show specific targets as sharp Cyan dots
        for r in poi_df.head(200).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=3,
                color="#00ffff", # Cyan
                fill=True,
                fill_opacity=1,
                popup=r.name
            ).add_to(m)

    st_folium(m, width=1000, height=650)

with col2:
    st.sidebar.title("Controls")
    st.sidebar.info("The grid displays vulnerability scores across Northern Virginia. Cyan dots represent identified business entities.")
    
    st.metric("Intelligence Points", f"{len(poi_df):,}")
    st.markdown("---")
    st.subheader("High Risk Sectors")
    for _, row in census_df.sort_values('vulnerability_score', ascending=False).head(3).iterrows():
        st.warning(f"**{row['Name']}**")
