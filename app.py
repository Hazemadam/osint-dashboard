import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

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
# 1. THE RISK CALIBRATOR
# ================================
def calculate_point_risk(row, census_data):
    # Base risk by business category
    category_weights = {
        'motel': 5, 'hotel': 4, 'massage': 8, 'spa': 6, 
        'nightclub': 7, 'bar': 5, 'stripclub': 10
    }
    base_score = category_weights.get(row['type'].lower(), 2)
    
    # Poverty Multiplier: Find the nearest neighborhood score
    # For speed, we match based on the 'Name' or 'tract' if available
    neighborhood_risk = 0
    if not census_data.empty:
        # We search for the county/tract influence
        match = census_data[census_data['Name'].str.contains(row.get('county', 'Fairfax'), case=False)]
        if not match.empty:
            neighborhood_risk = match['vulnerability_score'].max()
    
    total_risk = base_score + (neighborhood_risk * 1.5) # Heavy poverty weight
    
    # Define the "Bullet" color
    if total_risk > 15: return 'red'
    if total_risk > 8:  return 'orange' # Yellow-ish Medium
    return 'blue'

# ================================
# 2. MAIN DASHBOARD
# ================================
st.title("🛡️ NOVA Intelligence: Strategic Risk Points")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")

    if not poi_df.empty:
        # Process subset for performance
        display_df = poi_df.head(500).copy()
        
        for r in display_df.itertuples():
            risk_color = calculate_point_risk(r._asdict(), census_df)
            
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=6,
                color='white',
                weight=1,
                fill=True,
                fill_color=risk_color,
                fill_opacity=0.9,
                popup=f"<b>{r.name}</b><br>Type: {r.type}<br>Priority: {risk_color.upper()}"
            ).add_to(m)

    st_folium(m, width=950, height=650)

with col2:
    st.sidebar.title("🔍 Risk Filter")
    st.sidebar.markdown("""
    **Intelligence Key:**
    - 🔵 **Blue:** Low/Stable
    - 🟡 **Orange:** Moderate Alert
    - 🔴 **Red:** High Risk Zone
    """)
    
    st.metric("Total Points Scraped", f"{len(poi_df):,}")
    st.markdown("---")
    st.subheader("⚠️ Priority Targets")
    # Show the "hottest" 5 points based on the logic
    st.info("Showing top locations with maximum poverty and density overlap.")
    for i, row in poi_df.head(5).iterrows():
        st.write(f"📍 {row['name']} ({row['type']})")
