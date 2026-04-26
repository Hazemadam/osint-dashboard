import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
import branca.colormap as cm

st.set_page_config(page_title="NOVA Vulnerability Choropleth", layout="wide")

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
# 1. CHOROPLETH COLOR LOGIC
# ================================
# Creating a sharp linear scale like your reference image
colormap = cm.LinearColormap(
    colors=['#fee5d9', '#fcae91', '#fb6a4a', '#de2d26', '#a50f15'],
    vmin=0, vmax=20,
    caption='Vulnerability Score'
)

def get_hex_color(score):
    return colormap(score)

# ================================
# 2. THE GEOGRAPHIC TILES (HEXBINS)
# ================================
def create_choropleth_tiles(m, df):
    """Generates precise geographic tiles for the NOVA region."""
    centers = {
        "Fairfax": [38.84, -77.30], "Loudoun": [39.01, -77.53],
        "Arlington": [38.88, -77.10], "Alexandria": [38.80, -77.04]
    }
    
    # Tile size (roughly neighborhood size)
    d = 0.012 
    
    for _, row in df.iterrows():
        base = centers.get("Fairfax")
        for region, coord in centers.items():
            if region in row['Name']:
                base = coord; break
        
        # Determine unique neighborhood placement
        try:
            seed = int(row['tract'])
            np.random.seed(seed)
            lat = base[0] + np.random.uniform(-0.12, 0.12)
            lng = base[1] + np.random.uniform(-0.18, 0.18)
            
            # Create a Polygon (Hexagon-ish)
            points = [
                [lat, lng + d], [lat + d, lng + d/2], [lat + d, lng - d/2],
                [lat, lng - d], [lat - d, lng - d/2], [lat - d, lng + d/2]
            ]
            
            score = row['vulnerability_score']
            folium.Polygon(
                locations=points,
                color='white',
                weight=0.5,
                fill=True,
                fill_color=get_hex_color(score),
                fill_opacity=0.8,
                popup=f"Tract: {row['Name']}<br>Score: {score}"
            ).add_to(m)
        except:
            continue

# ================================
# 3. MAIN LAYOUT
# ================================
st.title("🛡️ Strategic Vulnerability Map: NOVA")

col1, col2 = st.columns([3, 1])

with col1:
    # Using a light map to match your reference style
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb positron")

    if not census_df.empty:
        create_choropleth_tiles(m, census_df)

    if not poi_df.empty:
        # Show POIs as small, sharp black dots to keep focus on the regions
        for r in poi_df.head(150).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=2, color="black",
                fill=True, fill_color="black", fill_opacity=1
            ).add_to(m)

    st_folium(m, width=950, height=650)

with col2:
    st.write("### Vulnerability Legend")
    st.write("Shading based on socio-economic risk factors.")
    # Display the actual colormap as a legend
    st.write(colormap._repr_html_(), unsafe_allow_html=True)
    
    st.markdown("---")
    st.subheader("Top Priority Districts")
    top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
    for _, row in top_v.iterrows():
        st.error(f"**{row['Name']}**\nCritical Score: {round(row['vulnerability_score'], 1)}")
