import streamlit as st
import io
from fpdf import FPDF
from agent import app as agent_app
from utils import sanitize_filename

# --- PAGE CONFIG ---
st.set_page_config(page_title="DFW Market Intel", page_icon="🎯", layout="wide")

# --- INITIALIZE SESSION STATES ---
# We use setdefault to keep the initialization clean
st.session_state.setdefault("all_logs", [])
st.session_state.setdefault("final_state", None)
st.session_state.setdefault("edit_subject", "")
st.session_state.setdefault("edit_body", "")

# --- SIDEBAR: TARGETING & CONTROLS ---
with st.sidebar:
    st.header("🎯 Target Parameters")
    niche = st.selectbox("Select Niche", ["Healthcare", "Logistics", "Real Estate", "Tech Infrastructure"])
    location = st.text_input("Location", "Dallas-Fort Worth, TX")
    
    st.divider()
    st.subheader("⚙️ Agent Settings")
    min_confidence = st.slider("Min. Confidence Threshold", 0.0, 1.0, 0.65, 0.05)
    
    if st.button("🗑️ Reset Session", use_container_width=True):
        st.session_state.all_logs = []
        st.session_state.final_state = None
        st.session_state.edit_subject = ""
        st.session_state.edit_body = ""
        st.rerun()

# --- MAIN UI ---
st.title("🎯 DFW Market-Intelligence Agent")
st.markdown(f"**Current Focus:** {niche} in **{location}**")

# --- INPUT SECTION ---
source_input = st.text_area(
    "Paste news snippet, press release, or lead data:",
    placeholder="e.g., 'A new medical complex is planned for Southlake near TX-114...'",
    height=150
)

# --- EXECUTION ---
if st.button("🚀 Run Intelligence Pipeline", type="primary"):
    if not source_input:
        st.error("Please provide a source for analysis.")
    else:
        st.session_state.all_logs = [] 
        
        initial_state = {
            "source_text": source_input,
            "niche": niche,
            "location": location,
            "logs": [],
            "status": "process"
        }

        # Expander with auto-scrolling log feel
        with st.expander("📜 Real-Time Agent Communication", expanded=True):
            log_container = st.empty()
            with st.spinner("Orchestrating Agent Nodes..."):
                try:
                    # Stream the graph execution
                    for output in agent_app.stream(initial_state):
                        for node_name, updated_values in output.items():
                            initial_state.update(updated_values)
                            if "logs" in updated_values:
                                new_log = f"📍 {node_name.upper()}: {updated_values['logs'][-1]}"
                                st.session_state.all_logs.append(new_log)
                                log_container.code("\n".join(st.session_state.all_logs))
                    
                    st.session_state.final_state = initial_state
                    
                    # Pre-fill editable fields for the email draft
                    email_data = initial_state.get("final_email", {})
                    st.session_state.edit_subject = email_data.get("subject", "")
                    st.session_state.edit_body = email_data.get("body", "")
                except Exception as e:
                    st.error(f"Workflow Exception: {e}")

# --- RESULTS DISPLAY ---
if st.session_state.final_state:
    final_state = st.session_state.final_state
    res = final_state.get("research_results", {})
    conf_score = res.get('confidence_score', 0)

    st.divider()

    # CONFIDENCE GATE
    if conf_score < min_confidence:
        st.warning(f"⚠️ Signal Confidence ({conf_score*100:.0f}%) below threshold ({min_confidence*100:.0f}%)")
        with st.expander("View Rejection Analysis"):
            st.json(res)
    
    elif final_state.get("status") == "process":
        st.success("✅ Market Signal Authenticated")
        col1, col2 = st.columns([1, 1.2])

        with col1:
            st.subheader("🔍 Research Insights")
            signal = res.get('verified_signal', 'N/A')
            st.markdown(f"**Top Signal:** <span style='color:#00FF00; font-weight:bold;'>{signal}</span>", unsafe_allow_html=True)
            st.metric("Lead Confidence", f"{conf_score*100:.0f}%")
            
            with st.expander("View Raw ROI & Signal Data", expanded=True):
                if final_state.get("roi_data"):
                    st.write("**ROI Analysis:**")
                    st.json(final_state["roi_data"])
                st.write("**Signal Data:**")
                st.json(res)

        with col2:
            st.subheader("📧 Outreach Strategy (Human-in-the-Loop)")
            
            # Use the session state to allow persistence of edits
            subj = st.text_input("Subject", value=st.session_state.edit_subject)
            body = st.text_area("Body", value=st.session_state.edit_body, height=350)
            st.session_state.edit_subject = subj
            st.session_state.edit_body = body

            # --- ACTION BUTTONS ---
            act_col1, act_col2 = st.columns(2)
            
            with act_col1:
                if subj.strip() and body.strip():
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", 'B', 16)
                    pdf.cell(0, 10, "DFW Market Intelligence Report", ln=True, align='C')
                    pdf.ln(10)
                    pdf.set_font("Arial", size=11)
                    pdf.multi_cell(0, 10, f"Signal: {signal}\nConfidence: {conf_score*100:.0f}%")
                    pdf.ln(5)
                    pdf.set_font("Arial", 'B', 12)
                    pdf.cell(0, 10, "Outreach Draft:", ln=True)
                    pdf.set_font("Arial", size=11)
                    pdf.multi_cell(0, 8, f"Subject: {subj}\n\n{body}")
                    
                    safe_loc = sanitize_filename(location)
                    st.download_button(
                        "💾 Download Intelligence PDF", 
                        data=pdf.output(dest='S').encode('latin-1'), 
                        file_name=f"Report_{safe_loc}.pdf", 
                        mime="application/pdf", 
                        use_container_width=True
                    )
                else:
                    st.button("💾 Download PDF", disabled=True, use_container_width=True)

            with act_col2:
                if st.button("📤 Send Outreach (Simulated)", use_container_width=True, type="primary"):
                    st.balloons()
                    st.success("✅ Outreach sent successfully (Simulated).")