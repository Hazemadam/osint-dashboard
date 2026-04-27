import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import numpy as np

# ================================
# 1. CONFIG & DATA LOADING
# ================================
st.set_page_config(page_title="NOVA Intelligence: Priority Map", layout="wide")

@st.cache_data(ttl=3600)
def load_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        return poi, census
    except Exception as e:
        st.error(f"Data loading failed: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# ================================
# 2. THE RISK ENGINE (Relative Scaling)
# ================================
def apply_relative_scoring(df, census):
    if df.empty:
        return df
    
    # Base risk by category
    weights = {'stripclub': 10, 'massage': 9, 'nightclub': 8, 'motel': 7, 'spa': 5, 'bar': 4, 'hotel': 2}
    
    # 1. Calculate raw scores
    raw_scores = []
    for _, row in df.iterrows():
        base = weights.get(row['type'].lower(), 1)
        poverty = 0
        if not census.empty:
            match = census[census['Name'].str.contains(row.get('county', 'Fairfax'), case=False)]
            poverty = match['vulnerability_score'].mean() if not match.empty else 0
        
        # We use a multiplier to make poverty scores (0.1 - 0.9) more impactful
        raw_scores.append(base + (poverty * 10))
    
    df['raw_score'] = raw_scores
    
    # 2. Determine Thresholds based on YOUR actual data range
    # This guarantees a mix of colors regardless of the raw values
    high_threshold = np.percentile(raw_scores, 90)  # Top 10%
    medium_threshold = np.percentile(raw_scores, 40) # Next 50%
    
    def get_color_label(s):
        if s >= high_threshold: return 'red', 'HIGH'
        if s >= medium_threshold: return 'orange', 'MEDIUM'
        return 'blue', 'LOW'
    
    df['color'], df['level'] = zip(*df['raw_score'].apply(get_color_label))
    return df

# ================================
# 3. SIDEBAR & FILTERS
# ================================
st.sidebar.title("🔍 Intelligence Filter")

if not poi_df.empty:
    # Initial dynamic scoring
    scored_df = apply_relative_scoring(poi_df, census_df)
    
    # Category Filter
    all_types = sorted(scored_df['type'].unique().tolist())
    requested_defaults = ['motel', 'massage', 'nightclub', 'stripclub']
    safe_defaults = [t for t in requested_defaults if t in all_types]
    
    selected_types = st.sidebar.multiselect("Business Category", all_types, default=safe_defaults)
    
    # Risk Priority Filter
    selected_risks = st.sidebar.multiselect("Risk Level", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM', 'LOW'])
    
    # APPLY FILTERS
    final_df = scored_df[(scored_df['type'].isin(selected_types)) & (scored_df['level'].isin(selected_risks))]
    
    # KEY FIX: Generate a unique ID for the map based on filter choices
    # This forces the map to refresh every time you change a filter
    map_id = f"map_{hash(tuple(selected_types))}_{hash(tuple(selected_risks))}"
else:
    final_df = pd.DataFrame()
    map_id = "empty_map"

st.sidebar.markdown("---")
st.sidebar.markdown("""
**Legend:**
- 🔴 **HIGH:** Top 10% Priority Targets
- 🟡 **MEDIUM:** Moderate Elevation
- 🔵 **LOW:** Standard Monitoring
""")

# ================================
# 4. MAIN LAYOUT
# ================================
st.title("🛡️ NOVA Strategic Risk Analysis")

col1, col2 = st.columns([3, 1])

with col1:
    # Use dark mode for visibility of high-priority red points
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

    # Adding the unique key=map_id fixes the update issue
    st_folium(m, width=900, height=650, key=map_id, returned_objects=[])

with col2:
    st.metric("Intelligence Points", len(poi_df))
    st.metric("Visible Targets", len(final_df))
    st.markdown("---")
    st.subheader("⚠️ Priority Alerts")
    
    # Show only High risk targets in the alert list
    alerts = final_df[final_df['level'] == 'HIGH'].head(10)
    if not alerts.empty:
        for _, row in alerts.iterrows():
            st.error(f"**{row['name']}**\n{row['type']}")
    else:
        st.info("Adjust filters to reveal High Priority targets.")
