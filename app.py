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
# 2. THE RISK ENGINE (Standardized Scoring)
# ================================
def apply_standardized_scoring(df, census):
    if df.empty:
        return df
    
    # Business weights
    weights = {
        'stripclub': 10, 'massage': 9, 'nightclub': 8, 
        'motel': 7, 'spa': 5, 'bar': 4, 'hotel': 2
    }
    
    raw_scores = []
    for _, row in df.iterrows():
        base = weights.get(row['type'].lower(), 1)
        poverty = 0
        if not census.empty:
            match = census[census['Name'].str.contains(row.get('county', 'Fairfax'), case=False)]
            poverty = match['vulnerability_score'].mean() if not match.empty else 0
        
        # Initial score combining the two
        raw_scores.append(base + (poverty * 5))
    
    df['raw_score'] = raw_scores
    
    # --- DYNAMIC BALANCING ---
    # We find the mean and standard deviation of YOUR data
    avg = np.mean(raw_scores)
    std = np.std(raw_scores)
    
    def get_color_label(s):
        # HIGH: More than 1 standard deviation above average
        if s > (avg + std): return 'red', 'HIGH'
        # MEDIUM: Above average
        if s > avg: return 'orange', 'MEDIUM'
        # LOW: Below average
        return 'blue', 'LOW'
    
    df['color'], df['level'] = zip(*df['raw_score'].apply(get_color_label))
    return df

# ================================
# 3. SIDEBAR & FILTERS
# ================================
st.sidebar.title("🔍 Intelligence Filter")

if not poi_df.empty:
    # 1. CATEGORY FILTER
    all_types = sorted(poi_df['type'].unique().tolist())
    requested_defaults = ['motel', 'massage', 'nightclub', 'stripclub']
    safe_defaults = [t for t in requested_defaults if t in all_types]
    
    selected_types = st.sidebar.multiselect("Business Category", all_types, default=safe_defaults)
    
    # Filter by type first
    filtered_df = poi_df[poi_df['type'].isin(selected_types)].copy()
    
    # 2. APPLY BALANCED SCORING
    scored_df = apply_standardized_scoring(filtered_df, census_df)
    
    # 3. RISK LEVEL FILTER
    selected_risks = st.sidebar.multiselect("Risk Level", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM', 'LOW'])
    
    final_df = scored_df[scored_df['level'].isin(selected_risks)]
    
    # Map ID to force refresh
    map_id = f"map_{hash(tuple(selected_types))}_{hash(tuple(selected_risks))}"
else:
    final_df = pd.DataFrame()
    map_id = "empty_map"

st.sidebar.markdown("---")
st.sidebar.markdown("""
**Risk Logic (Standardized):**
- 🔴 **HIGH:** Significantly above average risk.
- 🟡 **MEDIUM:** Above neighborhood average.
- 🔵 **LOW:** Below neighborhood average.
""")

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
                popup=f"<b>{r.name}</b><br>Risk: {r.level}<br>Score: {round(r.raw_score, 1)}"
            ).add_to(m)

    st_folium(m, width=900, height=650, key=map_id, returned_objects=[])

with col2:
    st.metric("Total Points Scored", len(scored_df) if not scored_df.empty else 0)
    st.metric("Visible on Map", len(final_df))
    st.markdown("---")
    st.subheader("⚠️ High Priority Alerts")
    
    alerts = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(10)
    if not alerts.empty:
        for _, row in alerts.iterrows():
            st.error(f"**{row['name']}**\nScore: {round(row['raw_score'], 1)}")
    else:
        st.info("No 'HIGH' outliers in the current selection.")
