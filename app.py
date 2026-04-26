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
# 1. UPDATED RISK CALIBRATOR
# ================================
def calculate_point_risk(row, census_data):
    # Base risk by business category
    category_weights = {
        'motel': 6, 'hotel': 3, 'massage': 7, 'spa': 5, 
        'nightclub': 8, 'bar': 4, 'stripclub': 10
    }
    base_score = category_weights.get(row['type'].lower(), 2)
    
    # Poverty Influence
    poverty_val = 0
    if not census_data.empty:
        # Match based on proximity or county if tract isn't available in POI
        # Adjusting the multiplier down (0.8) so it doesn't just turn everything red
        match = census_data[census_data['Name'].str.contains(row.get('county', 'Fairfax'), case=False)]
        if not match.empty:
            poverty_val = match['vulnerability_score'].mean() 
    
    total_risk = base_score + (poverty_val * 0.8)
    
    # RECALIBRATED THRESHOLDS:
    if total_risk > 12: return 'red', 'HIGH'
    if total_risk > 7:  return 'orange', 'MEDIUM' # Using orange for visibility
    return 'blue', 'LOW'

# ================================
# 2. SIDEBAR FILTERS
# ================================
st.sidebar.title("🔍 Intelligence Filters")

# Category Filter
if not poi_df.empty:
    all_types = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect("Business Categories", all_types, default=['motel', 'massage', 'nightclub'])
    
    # Pre-calculate risk for filtering
    poi_df['risk_data'] = poi_df.apply(lambda x: calculate_point_risk(x, census_df), axis=1)
    poi_df['color'] = poi_df['risk_data'].apply(lambda x: x[0])
    poi_df['level'] = poi_df['risk_data'].apply(lambda x: x[1])
    
    # Risk Level Filter
    selected_levels = st.sidebar.multiselect("Risk Level", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM', 'LOW'])
    
    # Apply Filters
    mask = (poi_df['type'].isin(selected_types)) & (poi_df['level'].isin(selected_levels))
    filtered_df = poi_df[mask]
else:
    filtered_df = pd.DataFrame()

st.sidebar.markdown("---")
st.sidebar.info("""
**Legend:**
- 🔴 **Red:** Critical Intersection (High Risk + High Poverty)
- 🟡 **Orange:** Moderate Concern
- 🔵 **Blue:** Lower Priority / Stable
""")

# ================================
# 3. MAIN DASHBOARD
# ================================
st.title("🛡️ NOVA Intelligence: Risk Point Analysis")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")

    if not filtered_df.empty:
        # Cap display at 1000 points for performance
        for r in filtered_df.head(1000).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=5,
                color='white',
                weight=0.5,
                fill=True,
                fill_color=r.color,
                fill_opacity=0.8,
                popup=f"<b>{r.name}</b><br>Type: {r.type}<br>Risk: {r.level}"
            ).add_to(m)

    st_folium(m, width=950, height=650)

with col2:
    st.metric("Total Entities", len(poi_df))
    st.metric("Filtered Results", len(filtered_df))
    
    st.markdown("---")
    st.subheader("⚠️ High Priority Targets")
    high_risk = filtered_df[filtered_df['level'] == 'HIGH'].head(10)
    for i, row in high_risk.iterrows():
        st.warning(f"**{row['name']}**\n{row['type']}")
