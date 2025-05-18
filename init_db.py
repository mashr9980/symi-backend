import psycopg2
import os
from psycopg2 import sql
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = {
    "dbname": 'postgres',
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "123"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

NEW_DATABASE_NAME = "chatbot-db"
try:
    # Connect to default 'postgres' database
    conn = psycopg2.connect(
        **DATABASE_URL
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Create new database
    cur.execute(sql.SQL("CREATE DATABASE {}").format(
        sql.Identifier(NEW_DATABASE_NAME)
    ))

    print(f"Database '{NEW_DATABASE_NAME}' created successfully!")

except Exception as e:
    print("Error:", e)

finally:
    if conn:
        cur.close()
        conn.close()
