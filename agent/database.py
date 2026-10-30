import os
import re
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SQLITE_DB_PATH = PROJECT_ROOT / "data" / "supply_chain.db"

# Schema documentation for the LLM agent
LEGACY_SCHEMA_DOCUMENTATION = """
Table: TBL_SC_FLEET_HIST_RAW (or dbo.TBL_SC_FLEET_HIST_RAW)
Description: Enterprise telemetry, warehouse operations, fleet performance, and order tracking logs.

Columns:
- TS_UTC (VARCHAR/DATETIME): Timestamp formatted as 'YYYY-MM-DD HH:MM:SS'. 
  * For shifts: 
    - Shift 1 (Early/Morning): Hours 06:00 to 14:00 (or 00:00 to 08:00)
    - Shift 2 (Afternoon/Day): Hours 14:00 to 22:00 (or 08:00 to 16:00)
    - Shift 3 (Night/Evening): Hours 22:00 to 06:00 (or 16:00 to 24:00)
  * To extract hour from TS_UTC, use: CAST(SUBSTR(TS_UTC, 12, 2) AS INT) or DATEPART(hour, TS_UTC).
- V_LAT (FLOAT): Vehicle GPS latitude coordinate.
- V_LON (FLOAT): Vehicle GPS longitude coordinate.
- FUEL_CONS_RATE (FLOAT): Vehicle fuel consumption rate (liters/hr or gal/hr).
- ETA_VAR_HRS (FLOAT): ETA variation in hours (higher = delay, lower/negative = early/on-time).
- TRF_CNG_LVL (FLOAT): Traffic congestion level along the transit route.
- WH_INV_LVL (FLOAT): Warehouse inventory level (units available).
- LOAD_UNLOAD_TM (FLOAT): Time taken for loading/unloading operations in hours.
- EQ_AVAIL_IND (FLOAT/INT): Material handling equipment availability indicator (1 = available, 0 = unavailable).
- ORD_FULFILL_STS (FLOAT): Order fulfillment status metric (1.0 = fulfilled, lower = delayed/partial).
- SYS_INGEST_FLAG (VARCHAR): Legacy ingestion flag ('Y').

Common Performance Metrics:
- Avg Delay: AVG(ETA_VAR_HRS)
- Avg Fuel Consumption: AVG(FUEL_CONS_RATE)
- Avg Loading/Dwell Time: AVG(LOAD_UNLOAD_TM)
- Fulfillment Rate: AVG(ORD_FULFILL_STS)
- Average Congestion: AVG(TRF_CNG_LVL)
"""

def get_engine():
    """
    Returns database engine:
    1. Attempts to connect to MSSQL Server if configured.
    2. Falls back to local/cloud SQLite file if MSSQL is unavailable.
    """
    host = os.getenv("SQL_server_HOST", os.getenv("SQL_SERVER_HOST", "localhost"))
    port = os.getenv("SQL_server_PORT", os.getenv("SQL_SERVER_PORT", "1433"))
    user = os.getenv("SQL_Admin_USER", os.getenv("SQL_ADMIN_USER", "sa"))
    password = os.getenv("SQL_Admin_PASSWORD", os.getenv("SQL_ADMIN_PASSWORD", "FdeEnterprisePass123!"))
    
    if os.getenv("FORCE_SQLITE", "false").lower() != "true":
        try:
            url = f"mssql+pymssql://{user}:{password}@{host}:{port}/master?login_timeout=2"
            mssql_engine = create_engine(url, pool_pre_ping=True)
            with mssql_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return mssql_engine, "MSSQL"
        except Exception:
            pass

    sqlite_url = f"sqlite:///{SQLITE_DB_PATH.as_posix()}"
    return create_engine(sqlite_url), "SQLite"

def execute_query(sql_query: str) -> dict:
    """Executes SQL query and returns records as list of dicts with dialect compatibility."""
    try:
        engine, dialect = get_engine()
        cleaned_query = sql_query.strip()
        
        # Dialect compatibility adjustments for SQLite
        if dialect == "SQLite":
            cleaned_query = re.sub(r"\bdbo\.", "", cleaned_query, flags=re.IGNORECASE)
            
            # Map T-SQL functions to SQLite equivalents
            cleaned_query = re.sub(r"DATEPART\s*\(\s*(hour|hh)\s*,\s*(\w+)\s*\)", r"CAST(SUBSTR(\2, 12, 2) AS INT)", cleaned_query, flags=re.IGNORECASE)
            cleaned_query = re.sub(r"HOUR\s*\(\s*(\w+)\s*\)", r"CAST(SUBSTR(\1, 12, 2) AS INT)", cleaned_query, flags=re.IGNORECASE)
            cleaned_query = re.sub(r"ISNULL\s*\(", "IFNULL(", cleaned_query, flags=re.IGNORECASE)
            cleaned_query = re.sub(r"LEN\s*\(", "LENGTH(", cleaned_query, flags=re.IGNORECASE)
            
            # Convert 'SELECT TOP N ...' to '... LIMIT N'
            top_match = re.search(r"SELECT\s+TOP\s+(\d+)\s+", cleaned_query, flags=re.IGNORECASE)
            if top_match:
                limit_n = top_match.group(1)
                cleaned_query = re.sub(r"SELECT\s+TOP\s+\d+\s+", "SELECT ", cleaned_query, flags=re.IGNORECASE)
                if not re.search(r"\bLIMIT\s+\d+", cleaned_query, flags=re.IGNORECASE):
                    cleaned_query = f"{cleaned_query.rstrip(';')} LIMIT {limit_n}"
            elif not re.search(r"\bLIMIT\s+\d+", cleaned_query, flags=re.IGNORECASE) and not re.search(r"\bCOUNT\(", cleaned_query, flags=re.IGNORECASE):
                cleaned_query = f"{cleaned_query.rstrip(';')} LIMIT 25"
                
        with engine.connect() as conn:
            result = conn.execute(text(cleaned_query))
            keys = result.keys()
            rows = [dict(zip(keys, row)) for row in result.fetchmany(50)]
            return {
                "success": True,
                "data": rows,
                "dialect": dialect,
                "executed_query": cleaned_query,
                "error": None
            }
    except Exception as e:
        return {
            "success": False,
            "data": None,
            "dialect": dialect if "dialect" in locals() else "Unknown",
            "executed_query": sql_query,
            "error": str(e)
        }
