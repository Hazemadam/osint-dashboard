import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
from serpapi import GoogleSearch

# ==========================================
# 1. INITIAL CONFIG & DEFAULTS
# ==========================================
st.set_page_config(page_title="NOVA Strategic Intelligence", layout="wide")

final_df = pd.DataFrame()
poi_df = pd.DataFrame()
census_df = pd.DataFrame()
serv_trend = pd.DataFrame()
sex_trend = pd.DataFrame()
loc_sex = pd.DataFrame()
loc_serv = pd.DataFrame()
threat_multiplier = 1.0
target = None

try:
    SERP_KEY = st.secrets["SERP_KEY"]
except:
    st.error("🔑 SERP_KEY missing in Secrets!")
    st.stop()

@st.cache_data(ttl=3600)
def load_all_intel():
    USER, REPO = "Hazemadam", "osint-dashboard"
    base = f"https://raw.githubusercontent.com/{USER}/{REPO}/main/"
    
    try:
        # Load the core parquet files
        p = pd.read_parquet(f"{base}nova_data.parquet")
        c = pd.read_parquet(f"{base}vulnerability_data.parquet")
        
        # Load your NEWLY RENAMED FBI files
        f_serv = pd.read_csv(f"{base}fbi_servitude.csv")
        f_sex = pd.read_csv(f"{base}fbi_sex_acts.csv")
        l_sex = pd.read_csv(f"{base}fbi_locations_sex_acts.csv")
        l_serv = pd.read_csv(f"{base}fbi_locations_servitude.csv")

        # Basic Cleanup
        p.columns = [col.lower().strip() for col in p.columns]
        if 'longitude' in p.columns: p = p.rename(columns={'longitude': 'lng', 'latitude': 'lat'})
        c.columns = [col.lower().strip() for col in c.columns]
        
        return p, c, f_serv, f_sex, l_sex, l_serv
    except Exception as e:
        # This will show you exactly which file name is still failing
        st.sidebar.error(f"File Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# Execute Load
poi_df, census_df, serv_trend, sex_trend, loc_sex, loc_serv = load_all_intel()

# ==========================================
# 2. INTELLIGENCE ENGINE
# ==========================================
def run_threat_assessment(poi, census, s_trend, x_trend, lsx, lsv):
    if poi.empty or s_trend.empty: return pd.DataFrame(), pd.Series(), 1.0
    
    # Combined trend multiplier (Offenses per month)
    combined = s_trend.iloc[0, 1:].astype(float) + x_trend.iloc[0, 1:].astype(float)
    multiplier = 1.35 if combined.tail(6).mean() > 5 else 1.0
    
    # Risk Weighting Logic
    sex_map = dict(zip(lsx['key'], lsx['value']))
    serv_map = dict(zip(lsv['key'], lsv['value']))
    county_risk = census.groupby('county')['vulnerability_score'].mean().to_dict()
    
    scores, colors, levels = [], [], []
    for _, row in poi.iterrows():
        # Match venue type to FBI risk data
        if any(x in str(row['type']) for x in ['motel', 'hotel', 'spa', 'massage']):
            base = sex_map.get('Hotel/Motel/Etc.', 10) / 5
        elif any(x in str(row['type']) for x in ['apartment', 'residential', 'home']):
            base = serv_map.get('Residence/Home', 5) / 2
        else:
            base = 5

        c_name = str(row.get('county', 'fairfax')).lower().replace(' county', '').strip()
        vuln = next((v for k, v in county_risk.items() if c_name in str(k).lower()), 0.5)
        
        # Calculate final threat tier
        fs = (base + (vuln * 10)) * multiplier
        scores.append(fs)
        
        if fs >= 22: colors.append('red'); levels.append('HIGH')
        elif fs >= 15: colors.append('orange'); levels.append('MEDIUM')
        else: colors.append('blue'); levels.append('LOW')
            
    poi['raw_score'], poi['color'], poi['level'] = scores, colors, levels
    return poi, combined, multiplier

# ==========================================
# 3. SIDEBAR & LOGIC
# ==========================================
st.sidebar.title("🛡️ NOVA Intel Command")

if not poi_df.empty and not serv_trend.empty:
    processed_df, master_trend, threat_multiplier = run_threat_assessment(
        poi_df, census_df, serv_trend, sex_trend, loc_sex, loc_serv
    )
    
    st.sidebar.metric("Regional Multiplier", f"{round(threat_multiplier, 2)}x")
    
    if not master_trend.empty:
        with st.sidebar.expander("📈 Regional Threat Trend"):
            st.line_chart(master_trend.tail(12))

    all_types = sorted(processed_df['type'].unique())
    selected_types = st.sidebar.multiselect("Venue Categories", all_types, default=all_types[:3])
    final_df = processed_df[processed_df['type'].isin(selected_types)]

    if not final_df.empty:
        st.sidebar.markdown("---")
        target = st.sidebar.selectbox("Select Target for OSINT", sorted(final_df['name'].unique()))
        if st.sidebar.button("Run Deep Scan"):
            with st.spinner("Scanning Google Maps..."):
                search = GoogleSearch({"engine": "google_maps", "q": f"{target} Northern Virginia", "api_key": SERP_KEY})
                res = search.get_dict()
                d_id = res.get("local_results", [{}])[0].get("data_id") if "local_results" in res else None
                if d_id:
                    revs = GoogleSearch({"engine": "google_maps_reviews", "data_id": d_id, "api_key": SERP_KEY}).get_dict().get("reviews", [])
                    flags = ['buzzer', 'locked', 'cash only', 'scared', 'after hours', 'back door']
                    found = [f for r in revs for f in flags if f in str(r.get("snippet", "")).lower()]
                    st.session_state['scan_results'] = {target: list(set(found)) if found else ["CLEAR"]}
else:
    st.sidebar.warning("📡 Waiting for data connection...")

# ==========================================
# 4. DASHBOARD VISUALS
# ==========================================
st.title("🛡️ NOVA Risk Intelligence")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=11, tiles="cartodb dark_matter")
    if not final_df.empty:
        for r in final_df.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng], radius=9, color='white', weight=0.7,
                fill=True, fill_color=r.color, fill_opacity=0.8,
                popup=f"<b>{r.name}</b><br>Score: {round(r.raw_score, 1)}<br>Tier: {r.level}"
            ).add_to(m)
    st_folium(m, width=900, height=550, key="nova_final_v9")

    if 'scan_results' in st.session_state and target in st.session_state['scan_results']:
        st.markdown("---")
        st.subheader(f"📄 Intelligence Report: {target}")
        res_list = st.session_state['scan_results'][target]
        if "CLEAR" in res_list: st.success("✅ No linguistic red-flags detected.")
        else: st.error(f"🚩 **Linguistic Red-Flags Detected:** {', '.join(res_list)}")

with col2:
    st.metric("Targets Identified", len(final_df))
    if not loc_sex.empty:
        st.info(f"**Primary Vector:** {loc_sex.iloc[0]['key']}")
    
    if not final_df.empty:
        st.markdown("---")
        watchlist = final_df.sort_values('raw_score', ascending=False).head(10)
        for _, row in watchlist.iterrows():
            icon = "🔴" if row['level'] == 'HIGH' else "🟠"
            st.write(f"{icon} **{row['name']}**")
            st.caption(f"Score: {round(row['raw_score'], 1)} | {row['type']}")
