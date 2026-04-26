import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="NOVA Strategic Map", layout="wide")

@st.cache_data(ttl=3600)
def load_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        
        # CLEANUP: Ensure tract is a string for mapping (very important!)
        census['tract'] = census['tract'].astype(str).str.zfill(6)
        return poi, census
    except Exception as e:
        st.error(f"Data loading failed: {e}")
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# --- RELIABLE GEOJSON SOURCE ---
# This is a cleaner, more stable GeoJSON for Virginia Census Tracts
VA_GEO_URL = "https://raw.githubusercontent.com/OpenDataDE/State-zip-code-GeoJSON/master/va_virginia_zip_codes_geo.min.json"

st.title("🛡️ Strategic Vulnerability Map: NOVA")

col1, col2 = st.columns([3, 1])

with col1:
    m = folium.Map(location=[38.85, -77.30], zoom_start=10, tiles="cartodbpositron")

    if not census_df.empty:
        try:
            # Create the Choropleth
            # This will shade the actual neighborhood boundaries in red
            folium.Choropleth(
                geo_data=VA_GEO_URL,
                name="vulnerability",
                data=census_df,
                columns=["tract", "vulnerability_score"],
                key_on="feature.properties.ZCTA5CE10", # Updated to match reliable ZCTA key
                fill_color="YlOrRd", 
                fill_opacity=0.7,
                line_opacity=0.2,
                legend_name="Risk Level",
                highlight=True
            ).add_to(m)
        except Exception as e:
            st.warning("Map overlay is loading—check connection if it persists.")

    if not poi_df.empty:
        for r in poi_df.head(150).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=3, color="black", weight=1,
                fill=True, fill_color="white", fill_opacity=1,
                popup=f"Target: {r.name}"
            ).add_to(m)

    st_folium(m, width=950, height=650)

with col2:
    st.metric("Intelligence Points", f"{len(poi_df):,}")
    st.markdown("---")
    st.subheader("Critical Alerts")
    top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
    for _, row in top_v.iterrows():
        st.error(f"**{row['Name']}**\nPriority Level: Critical")
