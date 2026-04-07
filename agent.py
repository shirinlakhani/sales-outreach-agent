import os
import json
from typing import TypedDict, Annotated, List
import operator

# Third-party libraries
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from firecrawl import FirecrawlApp

# Verified imports for all 5 system prompts
from prompts import (
    BRAIN_SYSTEM_PROMPT,
    SCOUT_SYSTEM_PROMPT,
    RESEARCHER_SYSTEM_PROMPT,
    STRATEGIST_SYSTEM_PROMPT,
    WRITER_SYSTEM_PROMPT
)

# Import Central Utils
from utils import safe_parse_json  # Integrated for robust output handling

load_dotenv()

# ==========================================
# STATE DEFINITION
# ==========================================
class AgentState(TypedDict):
    niche: str
    location: str
    brain_data: dict
    scout_data: dict
    source_text: str
    research_results: dict
    roi_data: dict
    final_email: dict
    status: str
    logs: Annotated[List[str], operator.add]

# ==========================================
# MODEL INITIALIZATION
# ==========================================
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-preview-09-2025",  # Compatibility ensured
    temperature=0.1  # Low temperature for structured JSON output
)

# ==========================================
# NODES
# ==========================================
def brain_node(state: AgentState):
    try:
        prompt = BRAIN_SYSTEM_PROMPT.format(niche=state["niche"], location=state["location"])
        response = llm.invoke([SystemMessage(content=prompt)])
        data = safe_parse_json(response.content) or {}
        return {
            "brain_data": data,
            "status": "process",
            "logs": [f"Brain Strategy: {data.get('theory_name', 'Default Strategy')}"]
        }
    except Exception as e:
        return {"status": "error", "logs": [f"Brain Node Error: {str(e)}"]}

def scout_node(state: AgentState):
    """Calls Firecrawl unless source_text is already provided."""
    if state.get("status") != "process":
        return state
    if state.get("source_text"):
        # Skip web search if manual source text is provided
        return {"status": "process", "logs": ["Scout skipped: source_text already provided."], "scout_data": {}, "source_text": state["source_text"]}

    try:
        api_key = os.getenv("FIRECRAWL_API_KEY")
        if not api_key:
            return {"status": "error", "logs": ["Missing FIRECRAWL_API_KEY"]}

        app = FirecrawlApp(api_key=api_key)
        query = state.get("brain_data", {}).get("search_query", "")

        if not query:
            return {"status": "skip", "logs": ["No search query provided."]}

        search_result = app.search(
            query,
            params={'limit': 1, 'scrapeOptions': {'formats': ['markdown']}}
        )

        if not search_result.get("data"):
            return {"status": "skip", "logs": ["Scout found no results for the query."]}

        top_result = search_result["data"][0]
        raw_text = top_result.get("markdown", "")
        source_url = top_result.get("url", "Unknown Source")

        return {
            "source_text": raw_text,
            "scout_data": {"source_url": source_url},
            "status": "process",
            "logs": [f"Scout harvested content from: {source_url}"]
        }
    except Exception as e:
        return {"status": "error", "logs": [f"Scout Node Error: {str(e)}"]}

def researcher_node(state: AgentState):
    if state.get("status") != "process":
        return state
    try:
        response = llm.invoke([
            SystemMessage(content=RESEARCHER_SYSTEM_PROMPT),
            HumanMessage(content=state.get("source_text", "No text provided."))
        ])
        data = safe_parse_json(response.content) or {}

        conf_score = data.get("confidence_score", 0)
        status = "process" if conf_score >= 0.65 else "skip"

        return {
            "research_results": data,
            "status": status,
            "logs": [f"Researcher Confidence: {conf_score*100:.0f}%"]
        }
    except Exception as e:
        return {"status": "error", "logs": [f"Researcher Node Error: {str(e)}"]}

def strategist_node(state: AgentState):
    if state.get("status") != "process":
        return state
    try:
        response = llm.invoke([
            SystemMessage(content=STRATEGIST_SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(state.get("research_results", {})))
        ])
        data = safe_parse_json(response.content) or {}
        return {
            "roi_data": data,
            "status": "process",
            "logs": ["Strategist mapped ROI and solution benchmarks."]
        }
    except Exception as e:
        return {"status": "error", "logs": [f"Strategist Node Error: {str(e)}"]}

def writer_node(state: AgentState):
    if state.get("status") != "process":
        return state
    try:
        context = {
            "verified_signal": state.get("research_results", {}).get("verified_signal", "Unknown"),
            "location": state.get("location", "Unknown"),
            "bottleneck_identified": state.get("roi_data", {}).get("bottleneck_identified", "Unknown"),
            "ai_agent_solution": state.get("roi_data", {}).get("ai_agent_solution", "Unknown"),
            "annual_revenue_recovered": state.get("roi_data", {}).get("annual_revenue_recovered", "Unknown")
        }

        response = llm.invoke([
            SystemMessage(content=WRITER_SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(context))
        ])
        data = safe_parse_json(response.content) or {}
        return {
            "final_email": data,
            "status": "process",
            "logs": ["Writer completed outreach draft."]
        }
    except Exception as e:
        return {"status": "error", "logs": [f"Writer Node Error: {str(e)}"]}

# ==========================================
# CONDITIONAL LOGIC
# ==========================================
def check_status(state: AgentState):
    return "continue" if state.get("status") == "process" else "end"

# ==========================================
# GRAPH CONSTRUCTION
# ==========================================
builder = StateGraph(AgentState)

builder.add_node("brain", brain_node)
builder.add_node("scout", scout_node)
builder.add_node("researcher", researcher_node)
builder.add_node("strategist", strategist_node)
builder.add_node("writer", writer_node)

builder.set_entry_point("brain")
builder.add_edge("brain", "scout")
builder.add_edge("scout", "researcher")

builder.add_conditional_edges(
    "researcher",
    check_status,
    {"continue": "strategist", "end": END}
)

builder.add_edge("strategist", "writer")
builder.add_edge("writer", END)

# Compile for export to app.py
app = builder.compile()