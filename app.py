import streamlit as st

st.set_page_config(page_title="DFW Market Intelligence", page_icon="🎯")

st.title("🎯 DFW Market-Intelligence Agent")
st.markdown("### Identify high-value signals in the Dallas-Fort Worth market.")

with st.sidebar:
    st.header("Settings")
    niche = st.selectbox("Select Niche", ["Healthcare", "Logistics", "Real Estate"])
    location = st.text_input("Location", "Dallas, TX")

if st.button("Start Research"):
    st.info(f"Launching agent to find {niche} signals in {location}...")
    # This is where we will eventually call your LangGraph agent!
    st.success("Check back in a second—I'm scanning the Dallas Business Journal!")