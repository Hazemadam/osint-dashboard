import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import numpy as np

# ================================
# 1. CONFIG & DATA LOADING
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

@st.cache_data(ttl=3600)
def load_and_process_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        # Load datasets
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        
        # Standardize column names for the POI (Business) data
        poi.columns = [c.lower().strip() for c in poi.columns]
        rename_map = {'longitude': 'lng', 'lon': 'lng', 'long': 'lng', 'latitude': 'lat'}
        poi = poi.rename(columns=rename_map)

        # Standardize census columns
        census.columns = [c.lower().strip() for c in census.columns]
        
        return poi, census
    except Exception as e:
        st.error(f"Data Loading Error: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_and_process_data()

# ================================
# 2. THE INTELLIGENCE ENGINE
# ================================
def apply_risk_logic(poi, census):
    if poi.empty or census.empty:
        return poi

    # 1. Create a County-Level Vulnerability Map
    # We group by county and take the mean vulnerability score
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    
    # 2. Risk weights for business types
    weights = {'stripclub': 12, 'massage': 10, 'nightclub': 9, 'motel': 8, 'spa': 5, 'bar': 4, 'hotel': 2}
    
    # 3. Apply Scoring
    results = []
    for _, row in poi.iterrows():
        base_weight = weights.get(str(row['type']).lower(), 1)
        
        # Get the specific risk for the county this business is in
        # Clean the county name to match (removes "County" or "City" suffix if present)
        raw_county = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        
        # Search the census dictionary for a match
        vulnerability = 0
        for c_name, v_score in county_risk.items():
            if raw_county in str(c_name).lower():
                vulnerability = v_score
                break
        
        # Formula: Business Type + (Environmental Vulnerability * 10)
        total_score = base_weight + (vulnerability * 10)
        results.append(total_score)
    
    poi['raw_score'] = results
    
    # 4. Standardized Balancing (The "Surgical" Spread)
    avg = poi['raw_score'].mean()
    std = poi['raw_score'].std() if poi['raw_score'].std() > 0 else 1
    
    def get_color_label(s):
        if s > (avg + std): return 'red', 'HIGH'
        if s > avg: return 'orange', 'MEDIUM'
        return 'blue', 'LOW'
    
    poi['color'], poi['level'] = zip(*poi['raw_score'].apply(get_color_label))
    return poi

# ================================
# 3. SIDEBAR & FILTERS
# ================================
st.sidebar.title("🔍 Intelligence Filter")

if not poi_df.empty:
    scored_df = apply_risk_logic(poi_df, census_df)
    
    all_types = sorted(scored_df['type'].unique().tolist())
    requested_defaults = ['motel', 'massage', 'nightclub']
    safe_defaults = [t for t in requested_defaults if t in all_types]
    
    selected_types = st.sidebar.multiselect("Business Category", all_types, default=safe_defaults)
    selected_risks = st.sidebar.multiselect("Priority Level", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM', 'LOW'])
    
    final_df = scored_df[(scored_df['type'].isin(selected_types)) & (scored_df['level'].isin(selected_risks))]
    map_id = f"map_{hash(tuple(selected_types))}_{hash(tuple(selected_risks))}"
else:
    final_df = pd.DataFrame()
    map_id = "empty"

# ================================
# 4. MAIN MAP
# ================================
st.title("🛡️ NOVA Strategic Risk Analysis")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    
    if not final_df.empty:
        for r in final_df.head(1000).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=6, color='white', weight=0.5,
                fill=True, fill_color=r.color, fill_opacity=1,
                popup=f"<b>{r.name}</b><br>Priority: {r.level}<br>Risk Score: {round(r.raw_score, 1)}"
            ).add_to(m)
            
    st_folium(m, width=900, height=650, key=map_id)

with col2:
    st.metric("Total Points Scored", len(poi_df))
    st.metric("Visible Targets", len(final_df))
    st.markdown("---")
    st.subheader("⚠️ Priority Alerts")
    
    high_hits = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(10)
    if not high_hits.empty:
        for _, row in high_hits.iterrows():
            st.error(f"**{row['name']}**\nScore: {round(row['raw_score'], 1)}")
    else:
        st.info("No 'HIGH' outliers in current filter.")
