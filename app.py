import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="NOVA Vulnerability Choropleth", layout="wide")

@st.cache_data(ttl=3600)
def load_data():
    USER = "Hazemadam"
    REPO = "osint-dashboard"
    try:
        # Load your neighborhood scores
        census = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/vulnerability_data.parquet")
        # Load your intelligence points
        poi = pd.read_parquet(f"https://raw.githubusercontent.com/{USER}/{REPO}/main/nova_data.parquet")
        return poi, census
    except:
        return pd.DataFrame(), pd.DataFrame()

poi_df, census_df = load_data()

# --- THE GEOGRAPHIC ENGINE ---
# This URL points to official Census boundary data for Virginia
VA_GEO_URL = "https://raw.githubusercontent.com/loganpowell/census-geojson/master/GeoJSON/51/2018/tract.json"

st.title("🛡️ Strategic Vulnerability Map: NOVA")

col1, col2 = st.columns([3, 1])

with col1:
    # Use a clean, light background similar to the reference image
    m = folium.Map(location=[38.85, -77.30], zoom_start=10, tiles="cartodbpositron")

    if not census_df.empty:
        # Create the Choropleth (The shaded neighborhood layer)
        folium.Choropleth(
            geo_data=VA_GEO_URL,
            name="Choropleth",
            data=census_df,
            columns=["tract", "vulnerability_score"], # Match Tract ID to Score
            key_on="feature.properties.TRACTCE",      # The ID inside the GeoJSON
            fill_color="Reds",                        # Shades of red like the poverty map
            fill_opacity=0.7,
            line_opacity=0.2,
            legend_name="Vulnerability Score (%)",
            highlight=True
        ).add_to(m)

    if not poi_df.empty:
        # Overlay your intelligence points as small black markers
        for r in poi_df.head(100).itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lng],
                radius=3,
                color="black",
                fill=True,
                fill_opacity=1
            ).add_to(m)

    st_folium(m, width=950, height=650)

with col2:
    st.subheader("Map Controls")
    st.write("Shading represents official neighborhood boundaries.")
    st.markdown("---")
    st.subheader("Critical Zones")
    top_v = census_df.sort_values('vulnerability_score', ascending=False).head(5)
    for _, row in top_v.iterrows():
        st.error(f"**{row['Name']}**\nScore: {round(row['vulnerability_score'], 1)}")
