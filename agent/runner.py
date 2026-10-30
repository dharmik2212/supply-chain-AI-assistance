import sys
from pathlib import Path

# Fix Windows cp1252 stdout encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.graph import create_agent

def run_query(user_question: str):
    print("\n" + "=" * 50)
    print(f"[Query]: {user_question}")
    print("=" * 50)
    
    app = create_agent()
    
    initial_state = {
        "question": user_question,
        "query_type": "GENERAL",
        "sql_query": None,
        "sql_result": None,
        "sql_error": None,
        "final_answer": None
    }
    
    result = app.invoke(initial_state)
    
    print(f"Route: {result.get('query_type')}")
    if result.get("sql_query"):
        print(f"\n[Generated SQL]:\n{result.get('sql_query')}")
    if result.get("sql_error"):
        print(f"\n[SQL Error]: {result.get('sql_error')}")
    elif result.get("sql_result") is not None:
        print(f"\n[Database Records Returned]: {len(result.get('sql_result'))} rows")
        print(f"Results: {result.get('sql_result')}")
        
    print(f"\n[AI Assistant Answer]:\n{result.get('final_answer')}\n")

if __name__ == "__main__":
    test_question = "What is the average ETA variation and fuel consumption rate for our fleet?"
    if len(sys.argv) > 1:
        test_question = " ".join(sys.argv[1:])
    run_query(test_question)
