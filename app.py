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
def load_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        return poi, census
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# ================================
# 2. THE RISK ENGINE (Fixed Calibration)
# ================================
def apply_risk_scoring(df, census):
    if df.empty:
        return df
    
    # Base weights for businesses
    weights = {'stripclub': 12, 'massage': 10, 'nightclub': 9, 'motel': 8, 'spa': 5, 'bar': 4, 'hotel': 3}
    
    scores = []
    for _, row in df.iterrows():
        # Get base business risk
        base = weights.get(row['type'].lower(), 2)
        
        # Get poverty score for the area
        poverty = 0
        if not census.empty:
            # Match by county/region name
            match = census[census['Name'].str.contains(row.get('county', 'Fairfax'), case=False)]
            poverty = match['vulnerability_score'].mean() if not match.empty else 0
        
        # FINAL CALCULATION: 
        # Business Risk + (Poverty Score * 1.5)
        # This creates enough "spread" for different colors
        scores.append(base + (poverty * 1.5))
    
    df['raw_score'] = scores
    
    # FIXED THRESHOLDS (Manually tuned for NOVA data)
    def get_color(s):
        if s > 18: return 'red', 'HIGH'
        if s > 12: return 'orange', 'MEDIUM'
        return 'blue', 'LOW'
    
    df['color'], df['level'] = zip(*df['raw_score'].apply(get_color))
    return df

# ================================
# 3. SIDEBAR CONTROLS
# ================================
st.sidebar.title("🔍 Intelligence Filters")

if not poi_df.empty:
    # 1. CATEGORY FILTER
    all_types = sorted(poi_df['type'].unique().tolist())
    requested_defaults = ['motel', 'massage', 'nightclub', 'stripclub']
    safe_defaults = [t for t in requested_defaults if t in all_types]
    
    selected_types = st.sidebar.multiselect("Business Categories", options=all_types, default=safe_defaults)
    
    # Filter by type FIRST
    filtered_by_type = poi_df[poi_df['type'].isin(selected_types)].copy()
    
    # 2. SCORE THE DATA
    scored_df = apply_risk_scoring(filtered_by_type, census_df)
    
    # 3. RISK LEVEL FILTER
    selected_risks = st.sidebar.multiselect("Priority Levels", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM', 'LOW'])
    
    # Final Dataframe for Map
    final_df = scored_df[scored_df['level'].isin(selected_risks)]
    
    # Unique key to force map update on filter change
    filter_key = f"map_{hash(tuple(selected_types))}_{hash(tuple(selected_risks))}"
else:
    final_df = pd.DataFrame()
    filter_key = "map_empty"

st.sidebar.markdown("---")
st.sidebar.markdown("""
### 🧭 Intelligence Key
- 🔴 **HIGH:** Critical Priority (>18)
- 🟡 **MEDIUM:** Elevated Priority (12-18)
- 🔵 **LOW:** Standard Priority (<12)
""")

# ================================
# 4. MAIN LAYOUT
# ================================
st.title("🛡️ NOVA Strategic Risk Analysis")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")

    if not final_df.empty:
        # Show points (Limit to 1000 for browser speed)
        for r in final_df.head(1000).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=6,
                color='white', weight=0.5,
                fill=True, fill_color=r.color, fill_opacity=1,
                popup=f"<b>{r.name}</b><br>Type: {r.type}<br>Risk: {r.level}<br>Score: {round(r.raw_score, 1)}"
            ).add_to(m)

    st_folium(m, width=900, height=650, key=filter_key, returned_objects=[])

with col2:
    st.metric("Total in Category", len(scored_df) if not scored_df.empty else 0)
    st.metric("Visible on Map", len(final_df))
    
    st.markdown("---")
    st.subheader("⚠️ Priority Targets")
    
    # Show only High and Medium targets in the sidebar list
    high_priority = final_df[final_df['level'].isin(['HIGH', 'MEDIUM'])].sort_values('raw_score', ascending=False).head(10)
    
    if not high_priority.empty:
        for _, row in high_priority.iterrows():
            if row['level'] == 'HIGH':
                st.error(f"**{row['name']}**\nScore: {round(row['raw_score'], 1)}")
            else:
                st.warning(f"**{row['name']}**\nScore: {round(row['raw_score'], 1)}")
    else:
        st.info("No priority targets in current filter.")
