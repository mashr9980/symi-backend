import psycopg2
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = {
    "dbname": os.getenv("DB_NAME", "chatbot_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "123"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

# Establish a database connection
def get_db_connection():
    return psycopg2.connect(**DATABASE_URL)