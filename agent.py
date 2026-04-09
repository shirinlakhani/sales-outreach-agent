import os
import json
import time
import asyncio
import logging
import shelve
from datetime import datetime
from typing import TypedDict, List, Any, Dict, Optional, Type

from pydantic import BaseModel, field_validator
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from firecrawl import FirecrawlApp

from utils import get_cutoff_date, truncate_text
from prompts import (
    BRAIN_SYSTEM_PROMPT,
    SCOUT_SYSTEM_PROMPT,
    RESEARCHER_SYSTEM_PROMPT,
    STRATEGIST_SYSTEM_PROMPT,
    WRITER_SYSTEM_PROMPT,
)

load_dotenv()

# ===============================
# Logging
# ===============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("DFW-Agent")

# ===============================
# Validate Env
# ===============================
if not os.getenv("FIRECRAWL_API_KEY"):
    logger.error("FIRECRAWL_API_KEY missing!")
    raise ValueError("FIRECRAWL_API_KEY missing. Scout node will fail.")

# ===============================
# Constants
# ===============================
DEFAULT_TIMEOUT = 60
MAX_CHARS = 4000
CACHE_FILE = "scout_cache"

PRIMARY_MODEL = "gemini-3.1-flash-lite-preview"
STABLE_FALLBACK = "gemini-3.1-flash-lite-preview"

SIGNALS = [
    "expansion", "new location", "opening", "hiring", "construction", "growth"
]

BUSINESS_TYPES = [
    "company", "office", "facility", "warehouse", "clinic",
    "store", "distribution center", "business"
]

SCOUT_CONFIG = {
    "locations": [
        "dallas", "fort worth", "arlington", "frisco", "plano",
        "irving", "mckinney", "forney", "southlake", "dfw"
    ],
    "social_domains": [
        "facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com"
    ],
    "skip_domains": [
        "indeed.com", "ziprecruiter.com", "glassdoor.com"
    ],
    "industry_keywords": {
        "general": [
            "expansion", "opening", "new location", "construction", "growth",
            "hiring", "announcement", "facility", "office", "project",
            "development", "new site"
        ]
    }
}

# ===============================
# Pydantic Schemas
# ===============================
class BrainOutput(BaseModel):
    industry: str
    theory_name: str
    primary_query: str
    fallback_queries: List[str]
    friction_target: str
    reasoning: str

    @field_validator("fallback_queries")
    @classmethod
    def must_have_queries(cls, v: List[str]):
        if len(v) < 5:
            raise ValueError("Need at least 5 fallback queries")
        return v

class ScoutOutput(BaseModel):
    source_text: str
    source_url: str
    status: str = "process"

class ResearchOutput(BaseModel):
    company_name: str
    location: str
    verified_signal: str
    evidence_quote: str
    confidence_score: float
    status: str = "process"

class StrategistOutput(BaseModel):
    bottleneck_identified: str
    ai_agent_solution: str
    monthly_hours_saved: int
    annual_revenue_recovered: str
    status: str = "process"

class WriterOutput(BaseModel):
    subject: str
    body: str
    status: str = "process"

# ===============================
# Agent State
# ===============================
class AgentState(TypedDict):
    niche: str
    location: str
    data: Dict[str, Any]
    source_text: str
    status: str
    force_refresh: Optional[bool]
    metrics: Dict[str, Any]
    node_errors: List[Dict[str, str]]
    logs: List[Dict[str, Any]]
    cutoff_date: Optional[str]

# ===============================
# Helpers
# ===============================
def get_status_safe(response: BaseModel, default: str = "process") -> str:
    return getattr(response, "status", default)

def extract_source_text(item):
    """Return the richest text available from Firecrawl result."""
    for attr in ["markdown", "content", "description"]:
        val = getattr(item, attr, None)
        if val:
            return str(val)
    metadata = getattr(item, "metadata", None)
    if metadata:
        for attr in ["markdown", "content", "description"]:
            val = getattr(metadata, attr, None)
            if val:
                return str(val)
    return ""

# ===============================
# LLM Runner with Quota-Aware Backoff
# ===============================
async def run_llm_with_backoff(system_prompt: str, user_input: str, schema: Type[BaseModel], max_retries: int = 3):
    last_error = ""
    for attempt in range(max_retries):
        model = PRIMARY_MODEL if attempt == 0 else STABLE_FALLBACK
        try:
            llm = ChatGoogleGenerativeAI(model=model, temperature=0)
            structured_llm = llm.with_structured_output(schema)
            full_input = f"{system_prompt}\n\nINPUT DATA:\n{user_input}"
            if last_error:
                full_input += f"\n\nRETRY: Previous error: {last_error}"
            res = await asyncio.wait_for(structured_llm.ainvoke(full_input), timeout=DEFAULT_TIMEOUT)
            if res:
                return res
            raise ValueError("Empty LLM response")
        except Exception as e:
            last_error = str(e)
            err_str = last_error.upper()
            if any(k in err_str for k in ["429", "RESOURCE_EXHAUSTED", "QUOTA"]):
                logger.error(f"Quota exceeded on {model}: {last_error}")
                raise RuntimeError(f"LLM quota exceeded: {last_error}")
            elif any(k in err_str for k in ["503", "UNAVAILABLE"]):
                wait_time = min(2 ** attempt + 1, 30)
                logger.warning(f"Transient LLM error ({model}): {last_error}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.warning(f"LLM error ({model}): {last_error}. Retrying in 2s...")
                await asyncio.sleep(2)
    raise RuntimeError(f"{schema.__name__} failed after {max_retries} attempts. Last error: {last_error}")

# ===============================
# Nodes
# ===============================
async def brain_node(state: AgentState):
    start = time.time()
    try:
        location = state["location"]
        query_candidates = [f"company {signal} {location}" for signal in SIGNALS]
        for bt in BUSINESS_TYPES:
            query_candidates.extend([
                f"new {bt} {location}",
                f"{bt} expansion {location}",
                f"{bt} hiring {location}"
            ])
        query_candidates = list(dict.fromkeys(query_candidates))
        primary_query = query_candidates[0]
        fallback_queries = query_candidates[1:6]
        result = BrainOutput(
            industry="general",
            theory_name="Generic Expansion Signal Search",
            primary_query=primary_query,
            fallback_queries=fallback_queries,
            friction_target="Organizations likely experiencing growth-related operational friction",
            reasoning="Using short natural-language search phrases because Firecrawl performs poorly on long Boolean queries."
        )
        logger.info(f"BRAIN node: primary_query='{primary_query}', fallback_queries={fallback_queries}")
        return {
            "data": {"brain": result.model_dump()},
            "status": "process",
            "metrics": {"brain_lat": time.time() - start, "query_count": len(query_candidates)},
            "logs": [{"node": "BRAIN", "message": f"Generated query strategy. Primary={primary_query}", "timestamp": datetime.now().isoformat()}]
        }
    except Exception as e:
        logger.exception("BRAIN node failed")
        return {"status": "error", "node_errors": [{"node": "BRAIN", "error": str(e)}]}

async def scout_node(state: AgentState):
    if state.get("status") == "error":
        return {"status": "error"}

    start = time.time()
    brain_data = state["data"].get("brain", {})
    queries = [brain_data.get("primary_query", "")] + brain_data.get("fallback_queries", [])
    queries = [q for q in queries if q]
    industry = brain_data.get("industry", "general").lower()
    KEYWORDS = SCOUT_CONFIG["industry_keywords"].get(industry, SCOUT_CONFIG["industry_keywords"]["general"])
    LOCATIONS = SCOUT_CONFIG["locations"]
    SOCIAL_DOMAINS = SCOUT_CONFIG["social_domains"]
    SKIP_DOMAINS = SCOUT_CONFIG["skip_domains"]

    firecrawl = FirecrawlApp(api_key=os.getenv("FIRECRAWL_API_KEY"))

    with shelve.open(CACHE_FILE) as db:
        for query in queries:
            if query in db and not state.get("force_refresh"):
                cached = db[query]
                logger.info(f"SCOUT cache hit query='{query}' url={cached['url']}")
                return {
                    "source_text": cached["text"],
                    "data": {"scout": cached},
                    "metrics": {"scout_lat": time.time() - start, "cache_hit": 1},
                    "status": "process",
                    "logs": [{"node": "SCOUT", "message": f"Cache hit for query='{query}'", "timestamp": datetime.now().isoformat()}]
                }

    best_candidate = None
    best_score = -1
    first_raw_result = None

    for query in queries:
        logger.info(f"SCOUT searching query='{query}'")
        try:
            raw_result = await asyncio.to_thread(firecrawl.search, query, limit=5, scrape_options={"formats": ["markdown"]})
            search_data = getattr(raw_result, "data", [])
            if not search_data:
                continue
            if not first_raw_result:
                first_item = search_data[0]
                first_raw_result = {
                    "text": extract_source_text(first_item),
                    "url": getattr(first_item, "url", "") or getattr(getattr(first_item, "metadata", None), "url", ""),
                    "title": getattr(first_item, "title", "") or getattr(getattr(first_item, "metadata", None), "title", "")
                }
            for idx, item in enumerate(search_data[:5]):
                text = extract_source_text(item)
                title = getattr(item, "title", "") or ""
                description = getattr(item, "description", "") or ""
                url = getattr(item, "url", "") or ""
                if not text:
                    text = f"{title}\n\n{description}"
                if len(text) < 80 or any(d in url.lower() for d in SKIP_DOMAINS):
                    continue
                combined = f"{title} {description} {text}".lower()
                score = 0
                reasons = []
                keyword_hits = [k for k in KEYWORDS if k.lower() in combined]
                if keyword_hits:
                    score += min(3, len(keyword_hits))
                    reasons.append(f"keywords={keyword_hits}")
                location_hits = [loc for loc in LOCATIONS if loc.lower() in combined]
                if location_hits:
                    score += min(2, len(location_hits))
                    reasons.append(f"locations={location_hits}")
                if len(text) > 500:
                    score += 2; reasons.append("long_text")
                elif len(text) > 150:
                    score += 1; reasons.append("medium_text")
                if len(description) > 50:
                    score += 1; reasons.append("usable_description")
                if any(d in url.lower() for d in SOCIAL_DOMAINS):
                    score += 1; reasons.append("social_source")
                if score > best_score:
                    best_score = score
                    best_candidate = {
                        "query": query, "url": url, "title": title, "description": description,
                        "text": text, "score": score, "reason": ", ".join(reasons),
                        "keyword_hits": keyword_hits, "location_hits": location_hits
                    }
        except Exception:
            logger.exception(f"SCOUT search error for query='{query}'")

    if best_candidate:
        with shelve.open(CACHE_FILE) as db:
            db[best_candidate["query"]] = {
                "text": best_candidate["text"],
                "url": best_candidate["url"],
                "title": best_candidate["title"],
                "score": best_candidate["score"],
                "reason": best_candidate["reason"]
            }
        return {
            "source_text": truncate_text(best_candidate["text"], MAX_CHARS),
            "data": {"scout": best_candidate},
            "metrics": {"scout_lat": time.time() - start, "cache_hit": 0, "score": best_candidate["score"]},
            "status": "process",
            "logs": [{"node": "SCOUT", "message": f"Best candidate selected query='{best_candidate['query']}' score={best_candidate['score']}", "timestamp": datetime.now().isoformat()}]
        }

    if first_raw_result:
        return {
            "source_text": truncate_text(first_raw_result["text"], MAX_CHARS),
            "data": {"scout": {"url": first_raw_result["url"], "title": first_raw_result.get("title", ""), "score": 0, "reason": "raw_fallback"}},
            "status": "process",
            "logs": [{"node": "SCOUT", "message": "Used raw fallback result", "timestamp": datetime.now().isoformat()}]
        }

    return {"status": "skip", "logs": [{"node": "SCOUT", "message": "No results found", "timestamp": datetime.now().isoformat()}]}

# ===============================
# Researcher, Strategist, Writer Nodes
# ===============================
async def researcher_node(state: AgentState):
    if state.get("status") in ["error", "skip"]:
        logger.info("RESEARCHER node skipped")
        return {"status": state.get("status")}
    start = time.time()
    source_text = state.get("source_text", "")
    if not source_text:
        logger.warning("RESEARCHER node has no source_text, skipping")
        return {"status": "skip"}
    logger.info("RESEARCHER node started")
    res = await run_llm_with_backoff(RESEARCHER_SYSTEM_PROMPT, truncate_text(source_text, MAX_CHARS), ResearchOutput)
    logger.info(f"RESEARCHER node completed in {time.time()-start:.2f}s")
    return {"data": {"research": res.model_dump()}, "status": get_status_safe(res), "metrics": {"research_lat": time.time() - start}, "logs":[{"node":"RESEARCHER","message":"Researcher node completed","timestamp":datetime.now().isoformat()}]}

async def strategist_node(state: AgentState):
    if state.get("status") in ["error", "skip"]:
        logger.info("STRATEGIST node skipped")
        return {"status": state.get("status")}
    start = time.time()
    res = await run_llm_with_backoff(STRATEGIST_SYSTEM_PROMPT, json.dumps(state["data"].get("research")), StrategistOutput)
    logger.info(f"STRATEGIST node completed in {time.time()-start:.2f}s")
    return {"data": {"roi": res.model_dump()}, "status": get_status_safe(res), "metrics": {"strategist_lat": time.time() - start}, "logs":[{"node":"STRATEGIST","message":"Strategist node completed","timestamp":datetime.now().isoformat()}]}

async def writer_node(state: AgentState):
    if state.get("status") in ["error", "skip"]:
        logger.info("WRITER node skipped")
        return {"status": state.get("status")}
    start = time.time()
    context = {"research": state["data"].get("research"), "roi": state["data"].get("roi")}
    res = await run_llm_with_backoff(WRITER_SYSTEM_PROMPT, json.dumps(context), WriterOutput)
    logger.info(f"WRITER node completed in {time.time()-start:.2f}s")
    return {"data": {"email": res.model_dump()}, "status": get_status_safe(res), "metrics": {"writer_lat": time.time() - start}, "logs":[{"node":"WRITER","message":"Writer node completed","timestamp":datetime.now().isoformat()}]}

# ===============================
# Router
# ===============================
def router(state: AgentState):
    return END if state.get("status") in ["error", "skip"] else "continue"

# ===============================
# Graph Orchestration
# ===============================
builder = StateGraph(AgentState)
builder.add_node("brain", brain_node)
builder.add_node("scout", scout_node)
builder.add_node("researcher", researcher_node)
builder.add_node("strategist", strategist_node)
builder.add_node("writer", writer_node)

builder.set_entry_point("brain")
builder.add_conditional_edges("brain", router, {"continue": "scout", END: END})
builder.add_conditional_edges("scout", router, {"continue": "researcher", END: END})
builder.add_conditional_edges("researcher", router, {"continue": "strategist", END: END})
builder.add_conditional_edges("strategist", router, {"continue": "writer", END: END})
builder.add_edge("writer", END)

app = builder.compile()

# ===============================
# Batch Runner
# ===============================
async def batch_run(niches=None, locations=None):
    niches = niches or ["retail expansion"]
    locations = locations or SCOUT_CONFIG["locations"]
    all_results = []
    for niche in niches:
        for loc in locations:
            state: AgentState = {
                "niche": niche,
                "location": loc,
                "data": {},
                "source_text": "",
                "status": "process",
                "force_refresh": False,
                "metrics": {},
                "node_errors": [],
                "logs": [],
                "cutoff_date": None
            }
            logger.info(f"Starting agent for niche='{niche}' location='{loc}'")
            try:
                result = await app.ainvoke(state)
                all_results.append({"niche": niche, "location": loc, "result": result})
                logger.info(f"Completed agent for {loc}, {niche}")
            except Exception as e:
                logger.exception(f"Agent failed for {loc}, {niche}: {e}")
    return all_results

# ===============================
# Main Entry
# ===============================
if __name__ == "__main__":
    niche = "AI Automation"
    location = "Frisco"

    results = asyncio.run(batch_run(niches=[niche], locations=[location]))
    print(json.dumps(results, indent=2))