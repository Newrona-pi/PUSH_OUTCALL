import requests
import json
import uuid

BASE_URL = "http://localhost:8000"

def run_verification():
    print("--- 1. Create Scenario ---")
    res = requests.post(f"{BASE_URL}/admin/scenarios/", json={
        "name": "Test Scenario", 
        "greeting_text": "こんにちは。テストです。",
        "disclaimer_text": "録音します。"
    })
    print(res.status_code, res.text)
    scenario_id = res.json()["id"]

    print("--- 2. Add Questions ---")
    requests.post(f"{BASE_URL}/admin/questions/", json={
        "text": "好きな食べ物は何ですか？",
        "sort_order": 1,
        "scenario_id": scenario_id
    })
    requests.post(f"{BASE_URL}/admin/questions/", json={
        "text": "趣味は何ですか？",
        "sort_order": 2,
        "scenario_id": scenario_id
    })

    print("--- 3. Map Phone Number ---")
    to_number = "+819012345678"
    requests.post(f"{BASE_URL}/admin/phone_numbers/", json={
        "to_number": to_number,
        "scenario_id": scenario_id,
        "label": "Test Line"
    })

    print("--- 4. Simulate Incoming Call ---")
    call_sid = str(uuid.uuid4())
    from_number = "+818098765432"
    res = requests.post(f"{BASE_URL}/twilio/voice", data={
        "To": to_number,
        "From": from_number,
        "CallSid": call_sid
    })
    print("Voice Response:", res.text)
    if "<Say>こんにちは。テストです。</Say>" in res.text:
        print(">> Greeting Verified")
    else:
        print(">> Greeting FAILED")

    print("--- 5. Simulate Recording Callback (Q1) ---")
    # Simulate answering Q1 (id=1, assumes id starts at 1)
    # The exact ID will be dynamic, so let's check logs or assume 1 for first run
    # Actually, let's fetch questions to get IDs
    q_res = requests.get(f"{BASE_URL}/admin/scenarios/{scenario_id}/questions")
    questions = q_res.json()
    q1_id = questions[0]["id"]
    q2_id = questions[1]["id"]

    res = requests.post(f"{BASE_URL}/twilio/record_callback?scenario_id={scenario_id}&q_curr={q1_id}", data={
        "CallSid": call_sid,
        "RecordingUrl": "http://example.com/rec1.mp3",
        "RecordingSid": "RE111"
    })
    print("Record Response 1:", res.text)
    # Should contain Q2 text
    if "趣味は何ですか？" in res.text:
        print(">> Next Question Verified")

    print("--- 6. Simulate Recording Callback (Q2 - End) ---")
    res = requests.post(f"{BASE_URL}/twilio/record_callback?scenario_id={scenario_id}&q_curr={q2_id}", data={
        "CallSid": call_sid,
        "RecordingUrl": "http://example.com/rec2.mp3",
        "RecordingSid": "RE222"
    })
    print("Record Response 2:", res.text)
    if "ありがとうございました" in res.text:
        print(">> End Message Verified")
    
    print("--- 7. Verify Logs ---")
    res = requests.get(f"{BASE_URL}/admin/calls/?to_number={to_number}")
    logs = res.json()
    print("Log Count:", len(logs))
    if len(logs) > 0 and len(logs[0]["answers"]) == 2:
        print(">> Log Verified")
    else:
        print(">> Log FAILED")
        print("Logs filtered:", logs)
        # Debug: get all calls
        all_logs = requests.get(f"{BASE_URL}/admin/calls/").json()
        print("All Calls:", all_logs)

if __name__ == "__main__":
    try:
        run_verification()
    except Exception as e:
        print("Error:", e)
