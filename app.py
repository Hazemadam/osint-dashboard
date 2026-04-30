import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import numpy as np
from serpapi import GoogleSearch

# ================================
# 1. CONFIG & DATA LOADING
# ================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

@st.cache_data(ttl=3600)
def load_and_process_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        
        # Standardize Columns
        poi.columns = [c.lower().strip() for c in poi.columns]
        poi = poi.rename(columns={'longitude': 'lng', 'lon': 'lng', 'latitude': 'lat'})
        census.columns = [c.lower().strip() for c in census.columns]
        
        return poi, census
    except Exception as e:
        st.error(f"Data Loading Error: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_and_process_data()

# ================================
# 2. INTELLIGENCE ENGINE (The Brain)
# ================================
def apply_global_risk(poi, census):
    if poi.empty or census.empty:
        return poi
    
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    weights = {'stripclub': 12, 'massage': 10, 'nightclub': 9, 'motel': 8, 'spa': 5, 'bar': 4}
    
    scores = []
    for _, row in poi.iterrows():
        base = weights.get(str(row['type']).lower(), 1)
        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vulnerability = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0)
        scores.append(base + (vulnerability * 10))
    
    poi['raw_score'] = scores
    avg, std = poi['raw_score'].mean(), poi['raw_score'].std() or 1
    
    def get_risk_meta(s):
        if s > (avg + std): return 'red', 'HIGH'
        if s > avg: return 'orange', 'MEDIUM'
        return 'blue', 'LOW'
    
    poi['color'], poi['level'] = zip(*poi['raw_score'].apply(get_risk_meta))
    return poi

# ================================
# 3. SIDEBAR & SURGICAL FILTERS
# ================================
st.sidebar.title("🛡️ NOVA OSINT Control")

# Your Secret Key
api_key = st.sidebar.text_input("SerpApi Key", value="e8620ecba88a6a45350306e642ce3b86db601631dba000d19d23d4cd7c7c4550", type="password")

if not poi_df.empty:
    scored_df = apply_global_risk(poi_df, census_df)
    
    # --- FILTERS ---
    st.sidebar.subheader("Map Filters")
    s_types = st.sidebar.multiselect("Business Categories", sorted(scored_df['type'].unique()), default=['motel', 'massage', 'nightclub'])
    s_risks = st.sidebar.multiselect("Risk Levels", ['HIGH', 'MEDIUM', 'LOW'], default=['HIGH', 'MEDIUM'])
    
    final_df = scored_df[(scored_df['type'].isin(s_types)) & (scored_df['level'].isin(s_risks))]

    # --- DEEP SCANNER KEYWORDS ---
    flags = [
        # Worker Distress
        'tired', 'confused', 'exhausted', 'sleeping', 'scared', 'nervous', 'dont know', 'living there',
        # Odd Timing/Access
        'after hours', 'private party', 'late night', 'buzzer', 'back door', 'locked', 'window covered',
        # Law Enforcement
        'police', 'raid', 'undercover', 'illegal', 'sketchy', 'trap', 'assault', 'dangerous', 'arrest',
        # Coded Language
        'cash only', 'no receipt', 'extra', 'special', 'full service', 'forced', 'security guard'
    ]

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔍 Deep Scan Intelligence")
    if not final_df.empty:
        target = st.sidebar.selectbox("Select Target to Interrogate", sorted(final_df['name'].unique()))
        
        if st.sidebar.button("Run OSINT Review Scan"):
            with st.spinner(f"Interrogating Google for {target}..."):
                # Search for ID
                search = GoogleSearch({"engine": "google_maps", "q": f"{target} Northern Virginia", "api_key": api_key})
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id")
                
                if d_id:
                    # Get Reviews
                    rev_search = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": api_key})
                    reviews = rev_search.get_dict().get("reviews", [])
                    found = [f"Found: '{f}'" for r in reviews for f in flags if f in r.get("snippet", "").lower()]
                    
                    if found:
                        st.sidebar.error(f"🚩 {len(set(found))} RED FLAGS DETECTED")
                        # High-Priority Logic
                        critical = ['police', 'raid', 'scared', 'forced', 'arrest', 'locked']
                        if any(c in str(found) for c in critical):
                            st.sidebar.warning("🚨 CRITICAL: Immediate indicators of duress or law enforcement presence found.")
                        for f in set(found): st.sidebar.write(f"- {f}")
                    else:
                        st.sidebar.success("Clear: No indicators found in recent reviews.")
                else:
                    st.sidebar.warning("Could not find a digital ID for this target.")

# ================================
# 4. MAIN DASHBOARD & PRIORITY LIST
# ================================
st.title("🛡️ NOVA Strategic Risk Dashboard")
c1, c2 = st.columns([3, 1])

with c1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    for r in final_df.itertuples():
        folium.CircleMarker(
            location=[r.lat, r.lng], radius=7, color='white', weight=0.5,
            fill=True, fill_color=r.color, fill_opacity=0.8,
            popup=f"<b>{r.name}</b><br>Risk: {r.level}<br>Type: {r.type}"
        ).add_to(m)
    st_folium(m, width=850, height=600)

with c2:
    st.metric("Analyzed Targets", len(final_df))
    st.subheader("⚠️ Priority Watchlist")
    high_risk = final_df[final_df['level'] == 'HIGH'].sort_values('raw_score', ascending=False).head(5)
    for _, row in high_risk.iterrows():
        st.warning(f"**{row['name']}**")
        st.caption(f"Category: {row['type']} | Score: {round(row['raw_score'],1)}")
