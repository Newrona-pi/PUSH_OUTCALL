from fastapi import APIRouter, Request, Depends, Form, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from twilio.twiml.voice_response import VoiceResponse
from ..database import get_db
from .. import models
import os
import requests
from openai import OpenAI

router = APIRouter(
    prefix="/twilio",
    tags=["twilio"],
)

# Initialize OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

async def transcribe_with_whisper(answer_id: int, recording_url: str, recording_sid: str):
    """Transcribe audio using OpenAI Whisper API"""
    import time
    
    try:
        if not OPENAI_API_KEY:
            print("OpenAI API key not configured")
            return
        
        # Download audio from Twilio with retry logic
        audio_url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Recordings/{recording_sid}.mp3"
        
        max_retries = 5
        retry_delay = 2  # seconds
        audio_response = None
        
        for attempt in range(max_retries):
            audio_response = requests.get(audio_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            
            if audio_response.status_code == 200:
                break
            
            if attempt < max_retries - 1:
                print(f"Recording not ready yet (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print(f"Failed to download recording after {max_retries} attempts: {recording_sid}")
                return
        
        # Save temporarily
        temp_file = f"/tmp/{recording_sid}.mp3"
        with open(temp_file, 'wb') as f:
            f.write(audio_response.content)
            
        audio_bytes = os.path.getsize(temp_file)
        
        # Transcribe with Whisper
        start_time = time.time()
        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(temp_file, 'rb') as audio_file:
            # Use verbose_json to get duration
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ja",
                response_format="verbose_json"
            )
        processing_time = time.time() - start_time
        
        transcript_text = transcript.text
        audio_duration = getattr(transcript, 'duration', 0)
        
        # Update database
        from ..database import SessionLocal
        db = SessionLocal()
        # Phase 2: Guard with recording_sid check to prevent mismatch
        answer = db.query(models.Answer).filter(
            models.Answer.id == answer_id,
            models.Answer.recording_sid == recording_sid
        ).first()
        
        if answer:
            answer.transcript_text = transcript_text
            answer.transcript_status = "completed"
            
            # Log success with Phase 2 details
            log_entry = models.TranscriptionLog(
                answer_id=answer_id,
                service="openai_whisper",
                status="success",
                audio_bytes=audio_bytes,
                audio_duration=int(audio_duration),
                model_name="whisper-1",
                language="ja",
                request_payload=f"file={recording_sid}.mp3",
                response_payload=transcript_text[:1000] if transcript_text else "",
                processing_time=int(processing_time)
            )
            db.add(log_entry)
            
            db.commit()
        else:
            print(f"Warning: Answer mismatch or not found for id={answer_id}, sid={recording_sid}")

        db.close()
        
        # Clean up
        if os.path.exists(temp_file):
            os.remove(temp_file)
        print(f"Transcription completed for {recording_sid}: {transcript_text}")
        
    except Exception as e:
        print(f"Transcription error for {recording_sid}: {str(e)}")
        # Update status to failed and log
        from ..database import SessionLocal
        db = SessionLocal()
        answer = db.query(models.Answer).filter(
            models.Answer.id == answer_id,
            models.Answer.recording_sid == recording_sid
        ).first()
        
        if answer:
            answer.transcript_status = "failed"
            
            # Log failure
            log_entry = models.TranscriptionLog(
                answer_id=answer_id,
                service="openai_whisper",
                status="failed",
                audio_bytes=audio_bytes if 'audio_bytes' in locals() else 0,
                model_name="whisper-1",
                request_payload=f"file={recording_sid}.mp3",
                response_payload=str(e),
                processing_time=0
            )
            db.add(log_entry)
            
            db.commit()
        db.close()
        
        # Clean up
        temp_file = f"/tmp/{recording_sid}.mp3"
        if os.path.exists(temp_file):
            os.remove(temp_file)

async def transcribe_message_with_whisper(message_id: int, recording_url: str, recording_sid: str):
    """Transcribe Message audio using OpenAI Whisper API"""
    import time
    
    try:
        if not OPENAI_API_KEY: return
        
        # Download audio from Twilio with retry logic
        audio_url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Recordings/{recording_sid}.mp3"
        
        max_retries = 5
        retry_delay = 2
        audio_response = None
        
        for attempt in range(max_retries):
            audio_response = requests.get(audio_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            if audio_response.status_code == 200: break
            time.sleep(retry_delay)
            retry_delay *= 2
        
        if not audio_response or audio_response.status_code != 200:
            print(f"Failed to download message recording: {recording_sid}")
            return

        temp_file = f"/tmp/msg_{recording_sid}.mp3"
        with open(temp_file, 'wb') as f:
            f.write(audio_response.content)
            
        # Transcribe
        client = OpenAI(api_key=OPENAI_API_KEY)
        with open(temp_file, 'rb') as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ja"
            )
        
        # Update DB
        from ..database import SessionLocal
        db = SessionLocal()
        msg = db.query(models.Message).filter(models.Message.id == message_id).first()
        if msg:
            msg.transcript_text = transcript.text
            db.commit()
        db.close()
        
        if os.path.exists(temp_file):
            os.remove(temp_file)
            
    except Exception as e:
        print(f"Message transcription error: {e}")
        # Clean up
        temp_file = f"/tmp/msg_{recording_sid}.mp3"
        if os.path.exists(temp_file):
            os.remove(temp_file)

@router.post("/voice")
async def handle_incoming_call(
    request: Request,
    To: str = Form(...),
    From: str = Form(...),
    CallSid: str = Form(...),
    db: Session = Depends(get_db)
):
    # This is for incoming calls to Twilio numbers
    # We will use the same logic as outbound for consistency
    return await handle_call_logic(To, From, CallSid, "inbound", db)

@router.post("/outbound_handler")
async def handle_outbound_call(
    request: Request,
    To: str = Form(...),
    From: str = Form(...),
    CallSid: str = Form(...),
    scenario_id: int = Query(...),
    db: Session = Depends(get_db)
):
    # This is called when an outbound call is answered
    return await handle_call_logic(To, From, CallSid, "outbound", db, scenario_id)

async def handle_call_logic(To: str, From: str, CallSid: str, direction: str, db: Session, scenario_id: int = None):
    from twilio.rest import Client
    
    # 1. Lookup Scenario
    if scenario_id:
        scenario = db.query(models.Scenario).get(scenario_id)
    else:
        # Incoming logic
        phone_entry = db.query(models.PhoneNumber).filter(models.PhoneNumber.to_number == To).first()
        scenario = phone_entry.scenario if phone_entry else None

    # Create Call record
    call = models.Call(
        call_sid=CallSid,
        from_number=From,
        to_number=To,
        status="in-progress",
        direction=direction,
        scenario_id=scenario.id if scenario else None
    )
    
    # Start Full Call Recording
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        try:
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            rec = client.calls(CallSid).recordings.create()
            call.recording_sid = rec.sid
        except Exception as e:
            print(f"Failed to start full call recording: {e}")

    db.add(call)
    db.commit()

    vr = VoiceResponse()

    if not scenario or not scenario.is_active or (scenario.is_hard_stopped):
        vr.say("現在この番号は使われておりません。", language="ja-JP")
        return Response(content=str(vr), media_type="application/xml")

    # Use Media Stream for GPT-Realtime
    connect = vr.connect()
    from urllib.parse import urlparse
    parsed_base = urlparse(os.getenv("PUBLIC_BASE_URL", ""))
    base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
    ws_url = base_domain.replace("https://", "wss://").replace("http://", "ws://")
    connect.stream(url=f"{ws_url}/realtime/stream/{CallSid}")
            
    return Response(content=str(vr), media_type="application/xml")

@router.post("/bridge_twiml")
async def bridge_twiml(number: str = Query(...)):
    vr = VoiceResponse()
    vr.say("担当者にお繋ぎします。少々お待ちください。", language="ja-JP")
    vr.dial(number)
    return Response(content=str(vr), media_type="application/xml")

@router.post("/status_callback")
async def status_callback(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: int = Form(None),
    db: Session = Depends(get_db)
):
    call = db.query(models.Call).filter(models.Call.call_sid == CallSid).first()
    if call:
        call.status = CallStatus
        if CallDuration:
            call.duration = CallDuration
        
        # Auto Classification logic
        if not call.classification:
            if CallStatus == "completed":
                if CallDuration and CallDuration < 15:
                    call.classification = "冒頭15秒以内切断"
                elif call.bridge_executed:
                    call.classification = "担当者に繋いだ"
                else:
                    call.classification = "聞いたが担当者まで進まなかった"
        
        db.commit()
    return Response(content="OK", media_type="text/plain")

