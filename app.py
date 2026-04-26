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
# 2. THE RISK ENGINE (Dynamic Scaling)
# ================================
def apply_risk_scoring(df, census):
    if df.empty:
        return df
    
    # Base weights
    weights = {'stripclub': 10, 'massage': 9, 'nightclub': 8, 'motel': 8, 'spa': 5, 'bar': 4, 'hotel': 3}
    
    # Calculate Raw Scores
    scores = []
    for _, row in df.iterrows():
        base = weights.get(row['type'].lower(), 2)
        poverty = 0
        if not census.empty:
            match = census[census['Name'].str.contains(row.get('county', 'Fairfax'), case=False)]
            poverty = match['vulnerability_score'].mean() if not match.empty else 0
        
        # Formula: Base + Exponential Poverty growth
        scores.append(base + (poverty ** 1.8))
    
    df['raw_score'] = scores
    
    # DYNAMIC THRESHOLDS (Percentile based to ensure color variety)
    high_cutoff = np.percentile(scores, 85) # Top 15% are Red
    low_cutoff = np.percentile(scores, 30)  # Bottom 30% are Blue
    
    def get_color(s):
        if s >= high_cutoff: return 'red', 'HIGH'
        if s <= low_cutoff: return 'blue', 'LOW'
        return 'orange', 'MEDIUM'
    
    df['color'], df['level'] = zip(*df['raw_score'].apply(get_color))
    return df

# ================================
# 3. SIDEBAR CONTROLS
# ================================
st.sidebar.title("🔍 Intelligence Filters")

if not poi_df.empty:
    # Initial Scoring
    poi_df = apply_risk_scoring(poi_df, census_df)
    
    # Category Filter
    all_types = sorted(poi_df['type'].unique().tolist())
    requested_defaults = ['motel', 'massage', 'nightclub', 'stripclub']
    safe_defaults = [t for t in requested_defaults if t in all_types]
    
    selected_types = st.sidebar.multiselect("Business Categories", options=all_types, default=safe_defaults)
    
    # Risk Filter
    selected_risks = st.sidebar.multiselect("Priority Levels", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM', 'LOW'])
    
    # APPLY FILTERS
    final_df = poi_df[(poi_df['type'].isin(selected_types)) & (poi_df['level'].isin(selected_risks))]
    
    # Create a unique key based on filter state to force map refresh
    filter_key = f"map_{len(selected_types)}_{len(selected_risks)}_{hash(tuple(selected_types))}"
else:
    final_df = pd.DataFrame()
    filter_key = "map_empty"

st.sidebar.markdown("---")
st.sidebar.markdown("### 🧭 Intelligence Key\n- 🔴 **HIGH:** Top 15% Risk\n- 🟡 **MEDIUM:** Average Risk\n- 🔵 **LOW:** Bottom 30% Risk")

# ================================
# 4. MAIN LAYOUT
# ================================
st.title("🛡️ NOVA Strategic Risk Analysis")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")

    if not final_df.empty:
        for r in final_df.head(1000).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=6,
                color='white', weight=0.5,
                fill=True, fill_color=r.color, fill_opacity=1,
                popup=f"<b>{r.name}</b><br>Type: {r.type}<br>Risk: {r.level}"
            ).add_to(m)

    # The 'key=filter_key' ensures the map updates when filters change
    st_folium(m, width=900, height=650, key=filter_key, returned_objects=[])

with col2:
    st.metric("Total Entities", len(poi_df))
    st.metric("Active Targets", len(final_df))
    st.markdown("---")
    st.subheader("⚠️ Priority Alerts")
    high_hits = final_df[final_df['level'] == 'HIGH'].head(10)
    if not high_hits.empty:
        for _, row in high_hits.iterrows():
            st.error(f"**{row['name']}**\n{row['type']}")
    else:
        st.info("Adjust filters to see targets.")
