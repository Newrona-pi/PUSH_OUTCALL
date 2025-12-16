import requests
import json

BASE_URL = "http://localhost:8000"

def check_logs():
    print("--- Checking Logs ---")
    res = requests.get(f"{BASE_URL}/admin/calls/")
    logs = res.json()
    print(f"Total Logs: {len(logs)}")
    for log in logs:
        print(f"CallSid: {log.get('call_sid')} | To: {log.get('to_number')} | Answers: {len(log.get('answers'))}")

if __name__ == "__main__":
    check_logs()
