import re
from typing import TypedDict, Optional, List, Dict, Any, Generator
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage
from agent.database import LEGACY_SCHEMA_DOCUMENTATION, execute_query
from agent.llm import get_llm, DEFAULT_GROQ_MODEL, FALLBACK_GROQ_MODEL

class SupplyChainState(TypedDict):
    question: str
    query_type: str
    sql_query: Optional[str]
    sql_result: Optional[List[Dict[str, Any]]]
    sql_error: Optional[str]
    final_answer: Optional[str]

def classify_query(state: SupplyChainState) -> Dict[str, Any]:
    """Classifies query using a tiny token budget (max_tokens=10) to preserve rate limit."""
    router_prompt = """Classify this query for a supply chain fleet/warehouse database:
- 'SQL': if asking for ANY data, metrics, performance, shift analysis, delays, fuel, loading time, warehouse, vehicles.
- 'GENERAL': if asking for pure conceptual definitions only.

Query: """ + state["question"] + """\nAnswer ('SQL' or 'GENERAL'):"""

    try:
        # Use only 10 tokens to preserve TPM
        llm = get_llm(max_tokens=10)
        res = llm.invoke([HumanMessage(content=router_prompt)])
        decision = res.content.strip().upper()
        if "SQL" in decision:
            return {"query_type": "SQL"}
        return {"query_type": "GENERAL"}
    except Exception:
        # Fallback to keyword matching if rate-limited or error
        q = state["question"].lower()
        sql_keywords = [
            "delay", "eta", "fuel", "inventory", "stock", "warehouse", "gps", "location",
            "fulfillment", "status", "congestion", "traffic", "loading", "equipment",
            "how many", "average", "highest", "lowest", "count", "fleet", "shift", "performance", "metric"
        ]
        if any(k in q for k in sql_keywords):
            return {"query_type": "SQL"}
        return {"query_type": "GENERAL"}

def route_query(state: SupplyChainState) -> str:
    return state.get("query_type", "GENERAL")

def generate_sql_node(state: SupplyChainState) -> Dict[str, Any]:
    """Generates SQL query with a lean token budget (max_tokens=150)."""
    system_prompt = f"""You are an expert Enterprise Database Engineer for a Supply Chain Operations platform.
Given the schema below, generate a single valid SELECT query to answer the user request.
Only query the table TBL_SC_FLEET_HIST_RAW.

{LEGACY_SCHEMA_DOCUMENTATION}

Key Guidelines:
- Performance Metrics: Compute operational metrics like:
  ROUND(AVG(ETA_VAR_HRS), 2) AS avg_delay_hours,
  ROUND(AVG(FUEL_CONS_RATE), 2) AS avg_fuel_rate,
  ROUND(AVG(LOAD_UNLOAD_TM), 2) AS avg_loading_time,
  ROUND(AVG(ORD_FULFILL_STS), 2) AS fulfillment_rate,
  ROUND(AVG(TRF_CNG_LVL), 2) AS avg_traffic_congestion,
  COUNT(*) AS total_trips
- Shifts (Shift 1, Shift 2, Shift 3):
  Extract the hour from TS_UTC using: CAST(SUBSTR(TS_UTC, 12, 2) AS INT)
  * Shift 1 (Morning): BETWEEN 6 AND 13 (or BETWEEN 0 AND 7)
  * Shift 2 (Afternoon/Evening): BETWEEN 14 AND 21 (or BETWEEN 8 AND 15)
  * Shift 3 (Night): >= 22 OR < 6
- Return ONLY the executable SQL query. Do not wrap in markdown or backticks. No explanation.
"""
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"User question: {state['question']}")
    ]

    try:
        # Small max_tokens=150 avoids 429 token quota limits
        llm = get_llm(max_tokens=150)
        response = llm.invoke(messages)
    except Exception as e:
        if "429" in str(e) or "rate_limit" in str(e).lower():
            fallback_llm = get_llm(model_id=FALLBACK_GROQ_MODEL, max_tokens=150)
            response = fallback_llm.invoke(messages)
        else:
            raise e
    
    sql = response.content.strip()
    sql = re.sub(r"^```(sql)?", "", sql, flags=re.IGNORECASE).strip()
    sql = re.sub(r"```$", "", sql).strip()
    
    return {"sql_query": sql}

def execute_sql_node(state: SupplyChainState) -> Dict[str, Any]:
    """Executes the generated SQL query."""
    sql = state.get("sql_query")
    if not sql:
        return {"sql_error": "No SQL query generated.", "sql_result": None}
    
    exec_res = execute_query(sql)
    return {
        "sql_result": exec_res.get("data"),
        "sql_error": exec_res.get("error")
    }

def synthesize_response_node(state: SupplyChainState) -> Dict[str, Any]:
    """Synthesizes SQL query results or answers general supply chain questions."""
    llm = get_llm(max_tokens=550)
    
    if state.get("query_type") == "SQL":
        system_prompt = """You are an intelligent Supply Chain and Logistics AI Operations Assistant.
Analyze the database results for a supply chain operations manager.
Never say 'I do not have access to your data' — you have direct access to TBL_SC_FLEET_HIST_RAW.
Provide:
1. Executive Summary & Direct Metrics Answer
2. Operational Takeaways (Delays, Fuel efficiency, Fulfillment, Loading time)
3. Actionable Supply Chain Recommendations
"""
        user_content = f"""User Question: {state['question']}
Executed SQL: {state.get('sql_query')}
Query Execution Error: {state.get('sql_error')}
Query Results: {state.get('sql_result')}
"""
    else:
        system_prompt = """You are an enterprise Supply Chain & Logistics AI Assistant.
Provide a clear, professional, and accurate response to the user's logistics inquiry."""
        user_content = state["question"]
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content)
    ]
    
    try:
        response = llm.invoke(messages)
    except Exception as e:
        if "429" in str(e) or "rate_limit" in str(e).lower():
            fallback_llm = get_llm(model_id=FALLBACK_GROQ_MODEL, max_tokens=550)
            response = fallback_llm.invoke(messages)
        else:
            raise e
            
    return {"final_answer": response.content}

def create_agent():
    """Builds and compiles the LangGraph state machine."""
    workflow = StateGraph(SupplyChainState)
    
    workflow.add_node("classify", classify_query)
    workflow.add_node("generate_sql", generate_sql_node)
    workflow.add_node("execute_sql", execute_sql_node)
    workflow.add_node("synthesize", synthesize_response_node)
    
    workflow.add_edge(START, "classify")
    
    workflow.add_conditional_edges(
        "classify",
        route_query,
        {
            "SQL": "generate_sql",
            "GENERAL": "synthesize"
        }
    )
    
    workflow.add_edge("generate_sql", "execute_sql")
    workflow.add_edge("execute_sql", "synthesize")
    workflow.add_edge("synthesize", END)
    
    return workflow.compile()

def stream_agent_workflow(question: str) -> Generator[Dict[str, Any], None, None]:
    """
    Executes the classification and SQL execution, then streams the synthesized LLM response token-by-token.
    Includes token budgeting and automatic failover if rate-limited.
    """
    initial_state = {
        "question": question,
        "query_type": "GENERAL",
        "sql_query": None,
        "sql_result": None,
        "sql_error": None,
        "final_answer": None
    }
    
    # 1. Classify
    class_res = classify_query(initial_state)
    query_type = class_res.get("query_type", "GENERAL")
    initial_state["query_type"] = query_type
    
    sql_query = None
    sql_result = None
    sql_error = None
    
    # 2. If SQL, generate and execute
    if query_type == "SQL":
        sql_gen = generate_sql_node(initial_state)
        sql_query = sql_gen.get("sql_query")
        initial_state["sql_query"] = sql_query
        
        exec_res = execute_sql_node(initial_state)
        sql_result = exec_res.get("sql_result")
        sql_error = exec_res.get("sql_error")
        initial_state["sql_result"] = sql_result
        initial_state["sql_error"] = sql_error
    
    # Yield metadata (so UI can display SQL and dataframe immediately)
    yield {
        "type": "meta",
        "query_type": query_type,
        "sql": sql_query,
        "data": sql_result,
        "error": sql_error
    }
    
    # 3. Stream the synthesis response
    if query_type == "SQL":
        system_prompt = """You are an intelligent Supply Chain and Logistics AI Operations Assistant.
Analyze the database results for a supply chain operations manager.
Never say 'I do not have access to your data' — you have direct access to TBL_SC_FLEET_HIST_RAW.
Provide:
1. Executive Summary & Direct Metrics Answer
2. Operational Takeaways (Delays, Fuel efficiency, Fulfillment, Loading time)
3. Actionable Supply Chain Recommendations
"""
        user_content = f"""User Question: {question}
Executed SQL: {sql_query}
Query Execution Error: {sql_error}
Query Results: {sql_result}
"""
    else:
        system_prompt = """You are an enterprise Supply Chain & Logistics AI Assistant.
Provide a clear, professional, and accurate response to the user's logistics inquiry."""
        user_content = question

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content)
    ]
    
    # Token-budgeted LLM (max_tokens=550 strictly fits within the 1000 OTPM rate limit)
    llm = get_llm(max_tokens=550)
    
    try:
        for chunk in llm.stream(messages):
            if chunk.content:
                yield {
                    "type": "chunk",
                    "content": chunk.content
                }
    except Exception as e:
        if "429" in str(e) or "rate_limit" in str(e).lower():
            # Automatic failover to secondary model if Qwen is temporarily rate-limited
            fallback_llm = get_llm(model_id=FALLBACK_GROQ_MODEL, max_tokens=550)
            for chunk in fallback_llm.stream(messages):
                if chunk.content:
                    yield {
                        "type": "chunk",
                        "content": chunk.content
                    }
        else:
            raise e
