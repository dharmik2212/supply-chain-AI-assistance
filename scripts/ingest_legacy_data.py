from pathlib import Path
import pandas as pd
import urllib
import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

# __file__ is 'experiment/phase-0/ingest_legacy_data.py'
script_dir = Path(__file__).resolve().parent # points to experiment/phase-0
project_root = script_dir.parents[0] # climbs up 1 levels to project root

load_dotenv(project_root / ".env")

data_path = project_root / "data" / "raw" / "dynamic_supply_chain_logistics_dataset-selected-columns.csv"

db_host = os.getenv("SQL_SERVER_HOST", "localhost")
db_port = os.getenv("SQL_SERVER_PORT", "1433")
db_user = os.getenv("SQL_ADMIN_USER")
db_password = os.getenv("SQL_ADMIN_PASSWORD")

# 1. Load the raw dataset
print(f"Loading CSV from {data_path}...")
df = pd.read_csv(data_path)

# Debug: Print actual columns found in your file
print("Actual columns found in CSV:", df.columns.tolist())

# 2. Map your actual CSV columns to a messy 2000s legacy enterprise schema
legacy_mapping = {
    'timestamp': 'TS_UTC',
    'vehicle_gps_latitude': 'V_LAT',
    'vehicle_gps_longitude': 'V_LON',
    'fuel_consumption_rate': 'FUEL_CONS_RATE',
    'eta_variation_hours': 'ETA_VAR_HRS',
    'traffic_congestion_level': 'TRF_CNG_LVL',
    'warehouse_inventory_level': 'WH_INV_LVL',
    'loading_unloading_time': 'LOAD_UNLOAD_TM',
    'handling_equipment_availability': 'EQ_AVAIL_IND',
    'order_fulfillment_status': 'ORD_FULFILL_STS'
}

# Safely keep only the columns that actually exist in the CSV file to avoid KeyErrors
valid_columns = [col for col in legacy_mapping.keys() if col in df.columns]
df_legacy = df[valid_columns].rename(columns=legacy_mapping)

# Add a fake ingestion flag to make it look like an automated legacy system
df_legacy['SYS_INGEST_FLAG'] = 'Y'

# 3. Connect to Docker MSSQL Server
print("Connecting to legacy MSSQL Database...")
connection_string = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={db_host},{db_port};"
        f"DATABASE=master;"
        f"UID={db_user};"
        f"PWD={db_password};"
        f"Encrypt=no;"
        f"TrustServerCertificate=yes;"
    )

params = urllib.parse.quote_plus(connection_string)

# engine = create_engine(f"mssql+pyodbc:///?odbc_connect={params}")
# Replace the pyodbc connection string with this clean pymssql line:
engine = create_engine(f"mssql+pymssql://{db_user}:{db_password}@{db_host}:{db_port}/master")

# 4. Ingest data into the messy table name
table_name = 'TBL_SC_FLEET_HIST_RAW'
print(f"Ingesting into {table_name}. This may take a minute...")
df_legacy.to_sql(table_name, engine, if_exists='replace', index=False, schema='dbo')

print("✅ Legacy data ingestion complete!")