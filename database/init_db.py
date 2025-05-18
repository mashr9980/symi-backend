import subprocess
import os
from dotenv import load_dotenv

load_dotenv()
# import psycopg2
# 
# ---- CONFIGURATION ----
PG_DUMP_PATH = r"/usr/bin/pg_restore"

DUMP_FILE = 'local_db.dump'
# ---- 2. RESTORE TO RDS ----
RDS_DB_NAME = 'chatbot-db'
RDS_DB_USER = os.getenv("DB_USER", "postgres")
RDS_DB_PASSWORD = os.getenv("DB_PASSWORD", "123")
RDS_DB_HOST = os.getenv("DB_HOST", "localhost")
RDS_DB_PORT = os.getenv("DB_PORT", "5432")
print("Restoring to RDS...")
os.environ['PGPASSWORD'] = RDS_DB_PASSWORD
restore_command = [
    PG_DUMP_PATH,
    '-h', RDS_DB_HOST,
    '-U', RDS_DB_USER,
    '-p', RDS_DB_PORT,
    '-d', RDS_DB_NAME,
    '--verbose',
    "--no-owner",
    "--disable-triggers",
    '--role=' + RDS_DB_USER,
    '-c',
    DUMP_FILE
]
subprocess.run(restore_command, check=True)
print("Restore to RDS completed.")
