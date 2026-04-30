import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from serpapi import GoogleSearch

# ================================
# 1. CONFIG & DATA
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

@st.cache_data(ttl=3600)
def load_data():
    USER, REPO = "Hazemadam", "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        census.columns = [c.lower().strip() for c in census.columns]
        return poi, census
    except: return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# ================================
# 2. THE INTELLIGENCE ENGINE
# ================================
def apply_risk_logic(poi, census):
    if poi.empty: return poi
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    weights = {'stripclub': 12, 'massage': 10, 'nightclub': 9, 'motel': 8, 'spa': 5}
    
    poi['raw_score'] = [weights.get(str(r['type']).lower(), 1) + 
                        (county_risk.get(str(r.get('county')).lower(), 0) * 10) 
                        for _, r in poi.iterrows()]
    
    avg, std = poi['raw_score'].mean(), poi['raw_score'].std() or 1
    def get_meta(s):
        if s > (avg + std): return 'red', 'HIGH'
        if s > avg: return 'orange', 'MEDIUM'
        return 'blue', 'LOW'
    
    poi['color'], poi['level'] = zip(*poi['raw_score'].apply(get_meta))
    return poi

# ================================
# 3. SIDEBAR & SCANNER
# ================================
st.sidebar.title("🛡️ NOVA OSINT Control")
api_key = st.sidebar.text_input("SerpApi Key", value="e8620ecba88a6a45350306e642ce3b86db601631dba000d19d23d4cd7c7c4550", type="password")

if not poi_df.empty:
    scored_df = apply_risk_logic(poi_df, census_df)
    
    # --- FILTERS ---
    st.sidebar.subheader("Map Filters")
    s_types = st.sidebar.multiselect("Categories", sorted(scored_df['type'].unique()), default=['motel', 'massage'])
    s_risks = st.sidebar.multiselect("Risk Level", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM'])
    
    final_df = scored_df[(scored_df['type'].isin(s_types)) & (scored_df['level'].isin(s_risks))]

    # --- DEEP SCANNER ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔍 Deep Scan")
    target = st.sidebar.selectbox("Target", sorted(final_df['name'].unique()))
    
    if st.sidebar.button("Run Interrogation"):
        with st.spinner("Analyzing..."):
            search = GoogleSearch({"engine": "google_maps", "q": f"{target} Northern Virginia", "api_key": api_key})
            d_id = search.get_dict().get("local_results", [{}])[0].get("data_id")
            
            if d_id:
                revs = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": api_key}).get_dict().get("reviews", [])
                
                # CRITICAL KEYWORDS
                found = []
                for r in revs:
                    t = r.get("snippet", "").lower()
                    for f in flags: # Using the long list from above
                        if f in t: found.append(f)
                
                if found:
                    unique_flags = set(found)
                    st.sidebar.error(f"🚩 {len(unique_flags)} FLAGS FOUND")
                    # Special alert for worker distress
                    if any(w in unique_flags for w in ['scared', 'tired', 'confused', 'forced', 'raid']):
                        st.sidebar.warning("⚠️ CRITICAL: Human behavior indicators detected.")
                    for f in unique_flags: st.sidebar.write(f"- {f}")
                else: st.sidebar.success("No sketchy keywords found.")

# ================================
# 4. MAIN DASHBOARD
# ================================
st.title("🛡️ NOVA Strategic Risk Dashboard")
c1, c2 = st.columns([3, 1])

with c1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    for r in final_df.itertuples():
        folium.CircleMarker([r.lat, r.lng], radius=7, color='white', weight=0.5,
                            fill=True, fill_color=r.color, fill_opacity=0.8,
                            popup=f"<b>{r.name}</b><br>Risk: {r.level}").add_to(m)
    st_folium(m, width=800, height=550)

with c2:
    st.metric("Targets", len(final_df))
    st.subheader("⚠️ Priority List")
    for _, row in final_df[final_df['level'] == 'HIGH'].head(5).iterrows():
        st.warning(row['name'])
