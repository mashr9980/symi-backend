import psycopg2
from app.database import get_db_connection

# Create tables in PostgreSQL if not exists
def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role VARCHAR(20) CHECK (role IN ('admin', 'business_owner')) NOT NULL DEFAULT 'business_owner',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id) ON DELETE CASCADE,
            message TEXT NOT NULL,
            response TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create pricing_plans table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pricing_plans (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            description TEXT NOT NULL,
            price NUMERIC(10, 2) NOT NULL,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            duration_days INTEGER NOT NULL DEFAULT 365,
            features JSONB NOT NULL DEFAULT '[]',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            display_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Check if payment_status table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'payment_status'
        )
    """)
    
    table_exists = cursor.fetchone()[0]
    
    if not table_exists:
        # Create payment_status table with plan_id column
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_status (
                id SERIAL PRIMARY KEY,
                user_id INT REFERENCES users(id) ON DELETE CASCADE,
                status VARCHAR(20) CHECK (status IN ('free', 'premium')) NOT NULL DEFAULT 'free',
                payment_id VARCHAR(100),
                payment_amount INT,
                payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expiry_date TIMESTAMP,
                plan_id INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        # Check if plan_id column exists in payment_status
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns 
                WHERE table_name = 'payment_status' AND column_name = 'plan_id'
            )
        """)
        
        column_exists = cursor.fetchone()[0]
        
        if not column_exists:
            # Add plan_id column to existing payment_status table
            cursor.execute("""
                ALTER TABLE payment_status
                ADD COLUMN plan_id INT
            """)

    conn.commit()
    cursor.close()
    conn.close()

# Run table creation at startup
# create_tables()