import sqlite3
import os

db_path = "./app.db"

if not os.path.exists(db_path):
    print("Database not found, models initialized via main app startup usually.")
    exit()

conn = sqlite3.connect(db_path)
c = conn.cursor()

def add_column(table, col, dtype):
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
        print(f"- Added {col} to {table}")
    except Exception as e:
        print(f"- Skipped {table}.{col}: {e}")

# Scenarios
add_column("scenarios", "deleted_at", "TIMESTAMP")
add_column("scenarios", "conversation_mode", "VARCHAR DEFAULT 'A'")
add_column("scenarios", "start_time", "VARCHAR DEFAULT '10:00'")
add_column("scenarios", "end_time", "VARCHAR DEFAULT '18:00'")
add_column("scenarios", "is_active", "BOOLEAN DEFAULT 1")
add_column("scenarios", "is_hard_stopped", "BOOLEAN DEFAULT 0")
add_column("scenarios", "silence_timeout_short", "INTEGER DEFAULT 15")
add_column("scenarios", "silence_timeout_long", "INTEGER DEFAULT 60")
add_column("scenarios", "bridge_number", "VARCHAR")
add_column("scenarios", "sms_template", "TEXT")

# Calls
add_column("calls", "recording_sid", "VARCHAR")
add_column("calls", "direction", "VARCHAR DEFAULT 'inbound'")
add_column("calls", "classification", "VARCHAR")
add_column("calls", "bridge_executed", "BOOLEAN DEFAULT 0")
add_column("calls", "sms_sent_log", "BOOLEAN DEFAULT 0")
add_column("calls", "transcript_full", "TEXT")
add_column("calls", "duration", "INTEGER")

# New Tables
c.execute('''
    CREATE TABLE IF NOT EXISTS ending_guidances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scenario_id INTEGER,
        text VARCHAR,
        sort_order INTEGER DEFAULT 0,
        created_at TIMESTAMP,
        FOREIGN KEY(scenario_id) REFERENCES scenarios(id)
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        call_sid VARCHAR,
        recording_sid VARCHAR,
        recording_url VARCHAR,
        transcript_text TEXT,
        created_at TIMESTAMP,
        FOREIGN KEY(call_sid) REFERENCES calls(call_sid)
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS call_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scenario_id INTEGER,
        phone_number VARCHAR,
        status VARCHAR DEFAULT 'pending',
        metadata_json TEXT,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        FOREIGN KEY(scenario_id) REFERENCES scenarios(id)
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS blacklist (
        phone_number VARCHAR PRIMARY KEY,
        reason VARCHAR,
        created_at TIMESTAMP
    )
''')

conn.commit()
conn.close()
print("Migration completed successfully.")
