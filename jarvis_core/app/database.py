import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"🔴 Critical: Database connection layer handshake failed: {str(e)}")
        sys.exit(1)

def initialize_database_schema():
    """Validates extensions, registers core relational schemas, and provisions CRM arrays."""
    commands = [
        "CREATE EXTENSION IF NOT EXISTS vector;",
        """
        CREATE TABLE IF NOT EXISTS leads_pipeline (
            id SERIAL PRIMARY KEY,
            business_email VARCHAR(255) UNIQUE NOT NULL,
            company_name VARCHAR(255),
            lead_score INT DEFAULT 0,
            outreach_stage VARCHAR(50) DEFAULT 'Sourced'
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS clients_crm (
            id SERIAL PRIMARY KEY,
            company_name VARCHAR(255) NOT NULL,
            industry_type VARCHAR(100),
            raw_requirements TEXT,
            contract_status VARCHAR(50) DEFAULT 'Prospect'
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS system_health_log (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            log_level VARCHAR(20) NOT NULL,
            subsystem VARCHAR(50) NOT NULL,
            message TEXT NOT NULL,
            traceback TEXT
        );
        """
    ]
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            for command in commands:
                cur.execute(command)
        conn.commit()
        print("🟢 System relational storage schemas successfully synchronized.")
    except Exception as e:
        print(f"🔴 Schema initialization failure sequence: {str(e)}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
