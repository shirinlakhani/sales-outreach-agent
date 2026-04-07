import os
from typing import TypedDict, Annotated, List
import operator
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv

# Load prompts from your prompts.py
from prompts import RESEARCHER_SYSTEM_PROMPT, COPYWRITER_SYSTEM_PROMPT

load_dotenv()

# ==========================================
# 🧠 STATE DEFINITION
# ==========================================
class AgentState(TypedDict):
    source_text: str
    niche: str
    location: str
    research_results: dict
    final_email: dict
    status: str
    logs: Annotated[List[str], operator.add]

# ==========================================
# 🤖 MODEL INITIALIZATION
# ==========================================
# We use Gemini 1.5 Flash for speed and high context window
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    temperature=0.2, # Low temperature for consistent JSON output
)

# ==========================================
# 🛠️ NODES (The "Workers")
# ==========================================

def researcher_node(state: AgentState):
    """Calls Gemini to analyze the growth signal and friction point."""
    print("--- STARTING RESEARCH ---")
    
    # Format the input for the Researcher
    input_data = {
        "source": "Manual Input",
        "company_name": "Unknown", # We'll let the model extract this
        "article_text": state["source_text"],
        "location": state["location"]
    }
    
    # Execute LLM Call
    response = llm.invoke([
        SystemMessage(content=RESEARCHER_SYSTEM_PROMPT),
        HumanMessage(content=str(input_data))
    ])
    
    # Parse the output (assuming JSON for now)
    import json
    try:
        results = json.loads(response.content)
        status = results.get("status", "skip")
        log_entry = f"Researcher found signal for {results.get('company')}: {status}"
    except Exception as e:
        results = {}
        status = "error"
        log_entry = f"Researcher failed to parse JSON: {str(e)}"

    return {
        "research_results": results,
        "status": status,
        "logs": [log_entry]
    }

def writer_node(state: AgentState):
    """Calls Gemini to draft the 'Triple-Hook' outreach."""
    if state["status"] == "skip":
        return {"logs": ["Writer skipped - Low relevance signal."]}
    
    print("--- STARTING OUTREACH DRAFT ---")
    
    response = llm.invoke([
        SystemMessage(content=COPYWRITER_SYSTEM_PROMPT),
        HumanMessage(content=str(state["research_results"]))
    ])
    
    import json
    try:
        email = json.loads(response.content)
        log_entry = "Writer successfully drafted outreach."
    except:
        email = {"subject": "Error", "body": "Failed to generate body."}
        log_entry = "Writer failed to generate valid JSON."

    return {
        "final_email": email,
        "logs": [log_entry]
    }