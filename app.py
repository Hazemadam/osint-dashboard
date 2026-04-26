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
# 1. THE RECALIBRATED FORMULA
# ================================
def get_risk_profile(row, census_data):
    # Base rates for business types
    weights = {'motel': 8, 'massage': 9, 'nightclub': 8, 'spa': 5, 'hotel': 3, 'bar': 4}
    base = weights.get(row['type'].lower(), 2)
    
    # Poverty Injection (Stretched)
    poverty = 0
    if not census_data.empty:
        # Match by county name
        match = census_data[census_data['Name'].str.contains(row.get('county', 'Fairfax'), case=False)]
        if not match.empty:
            poverty = match['vulnerability_score'].mean()
    
    # NEW FORMULA: Business weight + (Poverty squared / 5) 
    # Squaring the poverty makes the "bad" areas much redder
    total = base + ((poverty ** 2) / 5)
    
    if total > 18: return 'red', 'HIGH'
    if total > 10: return 'orange', 'MEDIUM'
    return 'blue', 'LOW'

# ================================
# 2. FILTERS & PROCESSING
# ================================
st.sidebar.title("🔍 Map Filters")

if not poi_df.empty:
    # 1. Business Category Filter
    types = sorted(poi_df['type'].unique().tolist())
    selected_types = st.sidebar.multiselect("Business Categories", types, default=['motel', 'massage', 'nightclub'])
    
    # Apply risk math to the whole dataframe
    poi_df['color'], poi_df['level'] = zip(*poi_df.apply(lambda x: get_risk_profile(x, census_df), axis=1))
    
    # 2. Risk Level Filter
    selected_risks = st.sidebar.multiselect("Risk Levels", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM'])
    
    # Final Filtered Data
    mask = (poi_df['type'].isin(selected_types)) & (poi_df['level'].isin(selected_risks))
    final_df = poi_df[mask]
else:
    final_df = pd.DataFrame()

# ================================
# 3. THE MAP
# ================================
st.title("🛡️ NOVA Strategic Risk: Bullet View")

col1, col2 = st.columns([3, 1])

with col1:
    # Dark map makes the colors (Red/Orange/Blue) pop
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")

    for r in final_df.head(800).itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng],
            radius=6,
            color='white', weight=0.5,
            fill=True, fill_color=r.color, fill_opacity=1,
            popup=f"<b>{r.name}</b><br>Risk: {r.level}"
        ).add_to(m)

    st_folium(m, width=900, height=600)

with col2:
    st.metric("Filtered Points", len(final_df))
    st.write("### Risk Breakdown")
    st.write(final_df['level'].value_counts())
    st.markdown("---")
    st.sidebar.markdown("""
    **Legend:**
    - 🔴 **Red:** Extreme Poverty + Risky Type
    - 🟡 **Orange:** High Density / Moderate Poverty
    - 🔵 **Blue:** Stable Area
    """)
