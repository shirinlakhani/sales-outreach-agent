import os
import json
import asyncio
from datetime import datetime
from fpdf import FPDF
import streamlit as st

from agent import app as agent_app
from utils import sanitize_filename, get_cutoff_date

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="DFW Market-Intelligence Agent",
    page_icon="🎯",
    layout="wide"
)

# --- SESSION STATE ---
for key, default in {
    "all_logs": [],
    "final_state": None,
    "edit_subject": "",
    "edit_body": "",
    "cutoff_override": "",
    "run_pipeline": False
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# --- HEADER ---
st.title("🎯 DFW Market-Intelligence Agent")
st.markdown("*Real-time prospecting for the North Texas market*")

# --- SIDEBAR ---
with st.sidebar:
    st.header("🎯 Target Parameters")
    niche = st.selectbox(
        "Industry Niche",
        ["Healthcare", "Logistics", "Real Estate", "General B2B"]
    )
    city = st.text_input("City", value="Frisco")

    st.subheader("⚙️ Agent Settings")
    force_refresh = st.checkbox("Force Cache Refresh", value=False)
    cutoff_override = st.text_input(
        "Cutoff Date (YYYY-MM-DD, optional)",
        value=st.session_state.cutoff_override
    )
    st.session_state.cutoff_override = cutoff_override

    if st.button("🗑️ Reset Session", use_container_width=True):
        for k in ["all_logs", "final_state", "edit_subject", "edit_body", "cutoff_override", "run_pipeline"]:
            st.session_state[k] = "" if isinstance(st.session_state[k], str) else None

# --- SOURCE INPUT ---
source_input = st.text_area(
    "Paste news snippet (optional):",
    height=100,
    placeholder="e.g., Texas Health is opening a new 50,000 sq ft facility in Frisco..."
)

# --- ASYNC PIPELINE RUNNER ---
async def run_pipeline(initial_state, log_placeholder):
    final_state = initial_state.copy()
    try:
        async for output in agent_app.astream(initial_state):
            if not output:
                continue

            for node_name, updated_values in output.items():
                if not updated_values:
                    continue

                # Append logs
                logs = updated_values.get("logs", [])
                for log_entry in logs:
                    ts = log_entry.get('timestamp', datetime.now().isoformat())
                    try:
                        formatted_ts = datetime.fromisoformat(ts).strftime('%H:%M:%S')
                    except:
                        formatted_ts = datetime.now().strftime('%H:%M:%S')
                    st.session_state.all_logs.append(f"[{formatted_ts}] 📍 {node_name.upper()}: {log_entry.get('message', '')}")

                log_placeholder.code("\n".join(st.session_state.all_logs))

                # Update data and metrics
                for key in ["data", "metrics", "node_errors", "status"]:
                    if key in updated_values:
                        if key not in final_state or not isinstance(final_state[key], dict):
                            final_state[key] = {} if key in ["data", "metrics"] else []
                        if isinstance(updated_values[key], dict):
                            final_state[key].update(updated_values[key])
                        else:
                            final_state[key].extend(updated_values[key]) if isinstance(updated_values[key], list) else None

    except RuntimeError as e:
        ts = datetime.now().strftime('%H:%M:%S')
        msg = f"[{ts}] 🚨 Pipeline runtime error: {str(e)}"
        st.session_state.all_logs.append(msg)
        log_placeholder.code("\n".join(st.session_state.all_logs))
        final_state["status"] = "error"
        final_state.setdefault("node_errors", []).append({"node": "PIPELINE", "error": str(e)})

    except Exception as e:
        ts = datetime.now().strftime('%H:%M:%S')
        msg = f"[{ts}] 🚨 Unexpected pipeline failure: {str(e)}"
        st.session_state.all_logs.append(msg)
        log_placeholder.code("\n".join(st.session_state.all_logs))
        final_state["status"] = "error"
        final_state.setdefault("node_errors", []).append({"node": "PIPELINE", "error": str(e)})

    finally:
        st.session_state.run_pipeline = False
    return final_state

# --- RUN PIPELINE TRIGGER ---
if st.button("🚀 Run Intelligence Pipeline", type="primary"):
    st.session_state.all_logs = ["System: Initializing pipeline..."]
    st.session_state.final_state = None
    st.session_state.run_pipeline = True

# --- PIPELINE EXECUTION ---
if st.session_state.run_pipeline:
    dfw_cities = ["Frisco", "Plano", "Irving", "Southlake", "Dallas", "Fort Worth", "Arlington"]
    initial_state = {
        "niche": niche,
        "location": city,
        "dfw_cities": dfw_cities,
        "source_text": source_input.strip(),
        "status": "process",
        "force_refresh": force_refresh,
        "cutoff_date": get_cutoff_date(st.session_state.cutoff_override),
        "data": {},
        "metrics": {},
        "node_errors": [],
        "logs": []
    }

    log_placeholder = st.empty()
    log_placeholder.code("\n".join(st.session_state.all_logs))

    with st.spinner("Orchestrating DFW Agent Nodes..."):
        final_output = asyncio.run(run_pipeline(initial_state, log_placeholder))
        st.session_state.final_state = final_output

        # Pre-fill edit areas if available
        email_data = final_output.get("data", {}).get("email", {})
        st.session_state.edit_subject = email_data.get("subject", "")
        st.session_state.edit_body = email_data.get("body", "")

# --- RESULTS DISPLAY ---
if st.session_state.final_state:
    state = st.session_state.final_state

    st.subheader("📜 Pipeline Logs")
    st.code("\n".join(st.session_state.all_logs))

    status = state.get("status", "")
    if status == "error":
        st.error("Pipeline encountered an error. Review logs above.")
    elif status == "skip":
        st.warning("No verified signals matched the criteria.")
    else:
        st.success("Analysis Complete!")

    col1, col2 = st.columns([1, 1.2])

    with col1:
        st.subheader("🔍 Research Insights")
        res_data = state.get("data", {}).get("research", {})
        st.write(f"**Company:** {res_data.get('company_name', 'N/A')}")
        st.write(f"**Location:** {res_data.get('location', 'N/A')}")
        st.write(f"**Signal:** {res_data.get('verified_signal', 'N/A')}")
        st.info(f"**Evidence Quote:**\n\"{res_data.get('evidence_quote', 'N/A')}\"")

        st.subheader("📊 ROI Strategy")
        roi_data = state.get("data", {}).get("roi", {})
        st.write(f"**Proposed AI Agent:** {roi_data.get('ai_agent_solution', 'N/A')}")
        st.metric("Monthly Hours Saved", f"{roi_data.get('monthly_hours_saved', 0)}h")
        st.metric("Revenue Recovered", roi_data.get('annual_revenue_recovered', 'N/A'))

    with col2:
        st.subheader("✍️ Outreach Draft")
        subj = st.text_input("Subject Line", value=st.session_state.edit_subject)
        body = st.text_area("Email Body", value=st.session_state.edit_body, height=350)
        st.session_state.edit_subject = subj
        st.session_state.edit_body = body

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if st.button("📤 Send Outreach", use_container_width=True, type="primary"):
                st.balloons()
                st.toast("Outreach sent!")

        with btn_col2:
            if st.button("📄 Export Report", use_container_width=True):
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("helvetica", 'B', 16)
                pdf.cell(0, 10, txt="DFW Market Intelligence Report", ln=True, align='C')
                pdf.ln(10)
                pdf.set_font("helvetica", 'B', 12)
                pdf.cell(0, 10, txt=f"Target: {res_data.get('company_name')}", ln=True)
                pdf.set_font("helvetica", '', 11)
                pdf.multi_cell(0, 10, txt=f"Signal: {res_data.get('verified_signal')}")
                pdf.ln(5)
                pdf.multi_cell(0, 10, txt=f"Draft:\n{st.session_state.edit_body}")
                st.download_button(
                    label="Download PDF",
                    data=pdf.output(dest='S'),
                    file_name=f"intel_{sanitize_filename(res_data.get('company_name', 'lead'))}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

st.divider()
st.caption("Built for North Texas Market Intelligence • 2026 Walkthrough")