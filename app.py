import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium

# ================================
# 1. CONFIG & DATA LOADING
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

@st.cache_data(ttl=3600)
def load_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        # Load business locations and census vulnerability data
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        return poi, census
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# ================================
# 2. THE RISK FORMULA (Recalibrated)
# ================================
def get_risk_profile(row, census_data):
    # Base risk weights for specific categories
    weights = {
        'stripclub': 10,
        'massage': 9,
        'nightclub': 8,
        'motel': 8,
        'spa': 5,
        'bar': 4,
        'hotel': 3
    }
    base_score = weights.get(row['type'].lower(), 2)
    
    # Poverty Injection Logic
    poverty_impact = 0
    if not census_data.empty:
        # Match by region string matching
        region_match = census_data[census_data['Name'].str.contains(row.get('county', 'Fairfax'), case=False)]
        if not region_match.empty:
            poverty_impact = region_match['vulnerability_score'].mean()
    
    # POWER FORMULA: (Poverty Squared / 4) + Base Weight
    # Squaring the poverty makes high-risk areas stand out aggressively in Red
    total_score = base_score + ((poverty_impact ** 2) / 4)
    
    # Color Thresholds
    if total_score > 20: 
        return 'red', 'HIGH'
    elif total_score > 10: 
        return 'orange', 'MEDIUM'
    else: 
        return 'blue', 'LOW'

# ================================
# 3. SIDEBAR CONTROLS (Safety Fixed)
# ================================
st.sidebar.title("🔍 Intelligence Filters")

if not poi_df.empty:
    # Pre-calculate risk metrics for the entire dataset
    poi_df['color'], poi_df['level'] = zip(*poi_df.apply(lambda x: get_risk_profile(x, census_df), axis=1))
    
    # 1. CATEGORY FILTER
    all_types = sorted(poi_df['type'].unique().tolist())
    
    # Safety Check: Only use defaults that actually exist in the data to prevent crash
    requested_defaults = ['motel', 'massage', 'nightclub', 'stripclub']
    safe_defaults = [t for t in requested_defaults if t in all_types]
    
    selected_types = st.sidebar.multiselect(
        "Business Categories", 
        options=all_types, 
        default=safe_defaults
    )
    
    # 2. RISK PRIORITY FILTER
    selected_risks = st.sidebar.multiselect(
        "Priority Levels", 
        ['HIGH', 'MEDIUM', 'LOW'], 
        default=['HIGH', 'MEDIUM']
    )
    
    # Apply Filtering
    mask = (poi_df['type'].isin(selected_types)) & (poi_df['level'].isin(selected_risks))
    final_df = poi_df[mask]
else:
    final_df = pd.DataFrame()
    st.sidebar.warning("No intelligence data found.")

st.sidebar.markdown("---")
st.sidebar.markdown("""
### 🧭 Intelligence Key
- 🔴 **HIGH:** Critical overlap of business type & poverty.
- 🟡 **MEDIUM:** Significant business risk or moderate poverty.
- 🔵 **LOW:** Stable environment / Low-risk category.
""")

# ================================
# 4. MAIN MAP DASHBOARD
# ================================
st.title("🛡️ NOVA Strategic Risk Analysis")

col1, col2 = st.columns([3, 1])

with col1:
    # Dark mode map for high-contrast "Bullet" visibility
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")

    if not final_df.empty:
        # Render the bullet points (limit to 1000 for browser speed)
        for r in final_df.head(1000).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=6,
                color='white',
                weight=0.5,
                fill=True,
                fill_color=r.color,
                fill_opacity=1,
                popup=f"<b>{r.name}</b><br>Type: {r.type}<br>Priority: {r.level}"
            ).add_to(m)

    st_folium(m, width=900, height=650, returned_objects=[])

with col2:
    st.metric("Total Entities", len(poi_df))
    st.metric("Priority Targets", len(final_df))
    
    st.markdown("---")
    st.subheader("⚠️ High Priority Alerts")
    # Display top HIGH risk targets for quick scanning
    high_priority = final_df[final_df['level'] == 'HIGH'].head(10)
    if not high_priority.empty:
        for i, row in high_priority.iterrows():
            st.error(f"**{row['name']}**\n{row['type']}")
    else:
        st.success("No High-Risk targets found in current view.")
