from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
import csv
import io
import os
import requests
import secrets
from datetime import datetime
from ..database import get_db
from .. import models, schemas

security = HTTPBasic()

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, "admin")
    correct_password = secrets.compare_digest(credentials.password, "attendme")
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_username)]
)

# Twilio credentials from environment
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

# --- Scenarios ---
@router.post("/scenarios/", response_model=schemas.Scenario)
def create_scenario(scenario: schemas.ScenarioCreate, db: Session = Depends(get_db)):
    db_scenario = models.Scenario(**scenario.dict())
    db.add(db_scenario)
    db.commit()
    db.refresh(db_scenario)
    return db_scenario

@router.put("/scenarios/{scenario_id}", response_model=schemas.Scenario)
def update_scenario(scenario_id: int, scenario: schemas.ScenarioCreate, db: Session = Depends(get_db)):
    db_scenario = db.query(models.Scenario).filter(models.Scenario.id == scenario_id).first()
    if not db_scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    for key, value in scenario.dict().items():
        setattr(db_scenario, key, value)
    
    db.commit()
    db.refresh(db_scenario)
    return db_scenario

@router.delete("/scenarios/{scenario_id}")
def delete_scenario(scenario_id: int, db: Session = Depends(get_db)):
    db_scenario = db.query(models.Scenario).filter(models.Scenario.id == scenario_id).first()
    if not db_scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    # Soft delete
    db_scenario.deleted_at = datetime.utcnow()
    # No longer deleting questions or phone number associations immediately
    # db.query(models.Question).filter(models.Question.scenario_id == scenario_id).delete()
    
    db.commit()
    return {"message": "Scenario deleted (soft)"}

@router.get("/scenarios/", response_model=List[schemas.Scenario])
def read_scenarios(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(models.Scenario).filter(models.Scenario.deleted_at.is_(None)).order_by(models.Scenario.id.desc()).offset(skip).limit(limit).all()

@router.get("/scenarios/{scenario_id}", response_model=schemas.Scenario)
def read_scenario(scenario_id: int, db: Session = Depends(get_db)):
    db_scenario = db.query(models.Scenario).options(
        joinedload(models.Scenario.ending_guidances)
    ).filter(models.Scenario.id == scenario_id).first()
    
    if db_scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return db_scenario

# --- Questions ---
@router.post("/questions/", response_model=schemas.Question)
def create_question(question: schemas.QuestionCreate, db: Session = Depends(get_db)):
    db_question = models.Question(**question.dict())
    db.add(db_question)
    db.commit()
    db.refresh(db_question)
    return db_question

@router.put("/questions/{question_id}", response_model=schemas.Question)
def update_question(question_id: int, question_update: schemas.QuestionBase, db: Session = Depends(get_db)):
    db_question = db.query(models.Question).filter(models.Question.id == question_id).first()
    if not db_question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    db_question.text = question_update.text
    db_question.sort_order = question_update.sort_order
    db_question.is_active = question_update.is_active
    
    db.commit()
    db.refresh(db_question)
    return db_question

@router.delete("/questions/{question_id}")
def delete_question(question_id: int, db: Session = Depends(get_db)):
    db_question = db.query(models.Question).filter(models.Question.id == question_id).first()
    if not db_question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    db.delete(db_question)
    db.commit()
    return {"message": "Question deleted"}

@router.get("/scenarios/{scenario_id}/questions", response_model=List[schemas.Question])
def read_questions_by_scenario(scenario_id: int, db: Session = Depends(get_db)):
    return db.query(models.Question).filter(
        models.Question.scenario_id == scenario_id
    ).order_by(models.Question.sort_order).all()

# --- Ending Guidance ---
@router.post("/ending_guidances/", response_model=schemas.EndingGuidance)
def create_ending_guidance(guidance: schemas.EndingGuidanceCreate, db: Session = Depends(get_db)):
    db_guidance = models.EndingGuidance(**guidance.dict())
    db.add(db_guidance)
    db.commit()
    db.refresh(db_guidance)
    return db_guidance

@router.put("/ending_guidances/{guidance_id}", response_model=schemas.EndingGuidance)
def update_ending_guidance(guidance_id: int, guidance_update: schemas.EndingGuidanceBase, db: Session = Depends(get_db)):
    db_guidance = db.query(models.EndingGuidance).filter(models.EndingGuidance.id == guidance_id).first()
    if not db_guidance:
        raise HTTPException(status_code=404, detail="Guidance not found")
    
    db_guidance.text = guidance_update.text
    db_guidance.sort_order = guidance_update.sort_order
    
    db.commit()
    db.refresh(db_guidance)
    return db_guidance

@router.delete("/ending_guidances/{guidance_id}")
def delete_ending_guidance(guidance_id: int, db: Session = Depends(get_db)):
    db_guidance = db.query(models.EndingGuidance).filter(models.EndingGuidance.id == guidance_id).first()
    if not db_guidance:
        raise HTTPException(status_code=404, detail="Guidance not found")
    
    db.delete(db_guidance)
    db.commit()
    return {"message": "Guidance deleted"}

@router.get("/scenarios/{scenario_id}/ending_guidances", response_model=List[schemas.EndingGuidance])
def read_ending_guidances_by_scenario(scenario_id: int, db: Session = Depends(get_db)):
    return db.query(models.EndingGuidance).filter(
        models.EndingGuidance.scenario_id == scenario_id
    ).order_by(models.EndingGuidance.sort_order).all()

# --- Phone Numbers ---
@router.post("/phone_numbers/", response_model=schemas.PhoneNumber)
def create_or_update_phone_number(phone: schemas.PhoneNumberCreate, db: Session = Depends(get_db)):
    # Normalize: ensure + prefix
    to_number = phone.to_number.strip()
    if not to_number.startswith('+'):
        to_number = '+' + to_number
    
    db_phone = db.query(models.PhoneNumber).filter(models.PhoneNumber.to_number == to_number).first()
    if db_phone:
        db_phone.scenario_id = phone.scenario_id
        db_phone.label = phone.label
        db_phone.is_active = phone.is_active
    else:
        db_phone = models.PhoneNumber(
            to_number=to_number,
            scenario_id=phone.scenario_id,
            label=phone.label,
            is_active=phone.is_active
        )
        db.add(db_phone)
    db.commit()
    db.refresh(db_phone)
    return db_phone

@router.delete("/phone_numbers/{to_number}")
def delete_phone_number(to_number: str, db: Session = Depends(get_db)):
    db_phone = db.query(models.PhoneNumber).filter(models.PhoneNumber.to_number == to_number).first()
    if not db_phone:
        raise HTTPException(status_code=404, detail="Phone number not found")
    db.delete(db_phone)
    db.commit()
    return {"message": "Phone number deleted"}

@router.get("/phone_numbers/", response_model=List[schemas.PhoneNumber])
def read_phone_numbers(db: Session = Depends(get_db)):
    return db.query(models.PhoneNumber).all()

# --- Recording Download ---
@router.get("/download_recording/{recording_sid}")
def download_recording(recording_sid: str):
    """Download a single recording from Twilio"""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="Twilio credentials not configured")
    
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Recordings/{recording_sid}.mp3"
    
    response = requests.get(url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), stream=True)
    
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Recording not found")
    
    return StreamingResponse(
        io.BytesIO(response.content),
        media_type="audio/mpeg",
        headers={"Content-Disposition": f"attachment; filename={recording_sid}.mp3"}
    )

@router.get("/download_call_recordings/{call_sid}")
def download_call_recordings(call_sid: str, db: Session = Depends(get_db)):
    """Download all recordings for a call as a ZIP file"""
    import pyzipper
    import re
    
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="Twilio credentials not configured")
    
    # Get all answers for this call
    answers = db.query(models.Answer).filter(models.Answer.call_sid == call_sid).all()
    # Also fetch Call for naming
    call = db.query(models.Call).filter(models.Call.call_sid == call_sid).first()
    
    if not answers and not (call and call.recording_sid):
        raise HTTPException(status_code=404, detail="No recordings found for this call")
    
    # Naming Helpers
    def sanitize(s): return re.sub(r'[\\/*?:"<>|]', "", s)
    
    date_part = call.started_at.strftime('%Y%m%d') if call else "00000000"
    sc_name = sanitize(call.scenario.name) if call and call.scenario else "NoScenario"
    to_num = call.to_number.replace('+','') if call else "000"
    from_num = call.from_number.replace('+','') if call else "000"
    short_sid = call_sid[-6:]
    
    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with pyzipper.AESZipFile(zip_buffer, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zip_file:
        zip_file.setpassword(b"attendme")
        zip_file.setencryption(pyzipper.WZ_AES, nbits=256)
        
        # 1. Full Recording
        if call and call.recording_sid:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Recordings/{call.recording_sid}.mp3"
            response = requests.get(url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            if response.status_code == 200:
                filename = f"{date_part}_{sc_name}_{to_num}_{from_num}_{short_sid}_FULL.mp3"
                zip_file.writestr(filename, response.content)

        # 2. Answers
        for idx, answer in enumerate(answers, 1):
            if answer.recording_sid:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Recordings/{answer.recording_sid}.mp3"
                response = requests.get(url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
                
                if response.status_code == 200:
                    filename = f"{date_part}_{sc_name}_{to_num}_{from_num}_{short_sid}_Q{idx}.mp3"
                    zip_file.writestr(filename, response.content)
    
    zip_buffer.seek(0)
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=call_{call_sid}_recordings.zip"}
    )

@router.get("/audio_proxy/{recording_sid}")
def proxy_audio_playback(recording_sid: str):
    """Proxy stream audio from Twilio for playback in admin UI"""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="Twilio credentials not configured")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Recordings/{recording_sid}.mp3"
    
    # Proxy without loading full content if possible, or simple get content
    # For <audio> tag seeking, range headers are complex.
    # Simple proxy: fetch entire content and stream back.
    
    response = requests.get(url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), stream=True)
    
    if response.status_code != 200:
         raise HTTPException(status_code=404, detail="Recording not found")
         
    return StreamingResponse(
        io.BytesIO(response.content), # Not truly streaming in this simple proxy implementation to avoid range complexity
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "public, max-age=3600"
        }
    )

# --- Logs & Stats ---
@router.get("/calls/", response_model=List[schemas.CallLog])
def read_calls(
    skip: int = 0, 
    limit: int = 100, 
    to_number: Optional[str] = None, 
    from_number: Optional[str] = None,
    start_date: Optional[str] = None,  # YYYY-MM-DD format
    end_date: Optional[str] = None,    # YYYY-MM-DD format
    scenario_status: str = "active",   # active or deleted
    db: Session = Depends(get_db)
):
    from datetime import datetime
    
    query = db.query(models.Call).options(
        joinedload(models.Call.answers).joinedload(models.Answer.question),
        joinedload(models.Call.scenario),
        joinedload(models.Call.messages)
    )
    
    # Scenario Status Filter
    if scenario_status == "active":
        query = query.join(models.Scenario).filter(models.Scenario.deleted_at.is_(None))
    elif scenario_status == "deleted":
        query = query.join(models.Scenario).filter(models.Scenario.deleted_at.isnot(None))
    
    if to_number:
        query = query.filter(models.Call.to_number == to_number)
    if from_number:
        query = query.filter(models.Call.from_number == from_number)
    
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(models.Call.started_at >= start_dt)
    if end_date:
        from datetime import timedelta
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(models.Call.started_at < end_dt)
        
    calls = query.order_by(models.Call.started_at.desc()).offset(skip).limit(limit).all()
    return calls 

@router.get("/export_zip")
def export_calls_zip(
    to_number: Optional[str] = None,
    from_number: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    scenario_status: str = "active",
    db: Session = Depends(get_db)
):
    import pyzipper
    from datetime import datetime, timedelta
    
    query = db.query(models.Call).options(
        joinedload(models.Call.answers).joinedload(models.Answer.question),
        joinedload(models.Call.scenario),
        joinedload(models.Call.messages)
    )
    
    if scenario_status == "active":
        query = query.join(models.Scenario).filter(models.Scenario.deleted_at.is_(None))
    elif scenario_status == "deleted":
        query = query.join(models.Scenario).filter(models.Scenario.deleted_at.isnot(None))
    
    if to_number:
        query = query.filter(models.Call.to_number == to_number)
    if from_number:
        query = query.filter(models.Call.from_number == from_number)
    
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(models.Call.started_at >= start_dt)
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(models.Call.started_at < end_dt)
    
    calls = query.order_by(models.Call.started_at.desc()).all()
    
    # helper for formatting
    def format_domestic(phone):
        if not phone: return ""
        if phone.startswith("+81"): return "0" + phone[3:]
        return phone
        
    stream = io.StringIO()
    writer = csv.writer(stream)
    
    writer.writerow(["CallSid", "Date", "To", "From", "ScenarioName", "Status", "Question", "AnswerType", "Transcript", "RecordingURL"])
    
    # Message CSV Stream
    msg_stream = io.StringIO()
    msg_writer = csv.writer(msg_stream)
    msg_writer.writerow(["CallSid", "ScenarioName", "Date", "RecordingUrl", "Transcript", "RecordingSid"])
    
    for call in calls:
        scenario_name = call.scenario.name if call.scenario else "Unknown"
        date_str = call.started_at.strftime("%Y-%m-%d %H:%M:%S")
        to_dom = format_domestic(call.to_number)
        from_dom = format_domestic(call.from_number)
        
        # Calls CSV
        if not call.answers:
            writer.writerow([
                call.call_sid, date_str, to_dom, from_dom, 
                scenario_name, call.status, "-", "-", "-", "-"
            ])
        else:
            for ans in call.answers:
                q_text = ans.question.text if ans.question else "Unknown"
                writer.writerow([
                    call.call_sid, date_str, to_dom, from_dom,
                    scenario_name, call.status, q_text, ans.answer_type, 
                    ans.transcript_text or "", 
                    ans.recording_url_twilio or ""
                ])
        
        # Messages CSV
        for msg in call.messages:
             msg_writer.writerow([
                 call.call_sid, scenario_name, date_str,
                 msg.recording_url or "",
                 msg.transcript_text or "",
                 msg.recording_sid or ""
             ])
                
    # Create ZIP in memory with AES encryption
    zip_buffer = io.BytesIO()
    with pyzipper.AESZipFile(zip_buffer, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(b"attendme")
        zf.setencryption(pyzipper.WZ_AES, nbits=256)
        
        today = datetime.now().strftime("%Y%m%d")
        csv_filename = f"{today}_logs.csv"
        zf.writestr(csv_filename, stream.getvalue())
        
        msg_filename = f"{today}_messages.csv"
        zf.writestr(msg_filename, msg_stream.getvalue())
        
    zip_buffer.seek(0)
    
    filename = f"logs_{datetime.now().strftime('%Y%m%d%H%M')}.zip"
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# --- Frontend Render ---
from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="app/templates")

@router.get("/dashboard")
def dashboard_ui(request: Request):
    import time
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "now_timestamp": int(time.time())
    })
# --- Phase 2: Retry Transcription ---
@router.post("/retranscribe/{answer_id}")
async def retry_transcription(answer_id: int, db: Session = Depends(get_db)):
    from .twilio import transcribe_with_whisper
    import asyncio
    
    answer = db.query(models.Answer).filter(models.Answer.id == answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")
    if not answer.recording_sid:
        raise HTTPException(status_code=400, detail="No recording SID available")
        
    # Reset status
    answer.transcript_status = "processing"
    db.commit()
    
    # Run async
    asyncio.create_task(transcribe_with_whisper(answer.id, answer.recording_url_twilio or "", answer.recording_sid))
    
    return {"message": "Transcription scheduled"}
