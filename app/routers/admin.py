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
import json
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

# --- Frontend Render (Multi-Page) ---
from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="app/templates")
import time

@router.get("/dashboard")
@router.get("/")
def dashboard_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/scenarios")

@router.get("/scenarios")
def scenarios_list_ui(request: Request):
    return templates.TemplateResponse("admin/scenarios_list.html", {
        "request": request,
        "active_page": "scenarios_list",
        "now_timestamp": int(time.time())
    })

@router.get("/scenarios/design")
def scenario_design_ui(request: Request, id: Optional[int] = None):
    return templates.TemplateResponse("admin/scenario_design.html", {
        "request": request,
        "active_page": "scenario_design",
        "scenario_id": id,
        "now_timestamp": int(time.time())
    })

@router.get("/outbound")
def outbound_ui(request: Request):
    return templates.TemplateResponse("admin/outbound.html", {
        "request": request,
        "active_page": "outbound",
        "now_timestamp": int(time.time())
    })

@router.get("/logs")
def logs_ui(request: Request):
    return templates.TemplateResponse("admin/logs.html", {
        "request": request,
        "active_page": "logs",
        "now_timestamp": int(time.time())
    })

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

# --- Outbound Targets ---
from fastapi import UploadFile, File

@router.post("/scenarios/{scenario_id}/upload_targets")
async def upload_targets(scenario_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read()
    
    # Try different encodings
    try:
        decoded = content.decode('utf-8-sig') # Handles UTF-8 BOM
    except UnicodeDecodeError:
        try:
            decoded = content.decode('cp932') # Handles Japanese Shift-JIS
        except UnicodeDecodeError:
            decoded = content.decode('utf-8', errors='ignore')

    lines = decoded.splitlines()
    reader = csv.DictReader(lines)
    
    # Clean headers (remove BOM or spaces)
    if reader.fieldnames:
        reader.fieldnames = [f.strip().replace('\ufeff', '') for f in reader.fieldnames]

    targets_added = 0
    for row in reader:
        # Support various possible header names for phone numbers
        phone = None
        for key in ['phone_number', '電話番号', 'tel', 'phone']:
            if key in row:
                phone = row[key]
                break
        
        if not phone: continue
        
        # Normalize
        phone = phone.strip()
        if not phone.startswith('+'):
            if phone.startswith('0'):
                phone = '+81' + phone[1:]
            else:
                phone = '+81' + phone
        
        # Check if already exists in this scenario
        existing = db.query(models.CallTarget).filter(
            models.CallTarget.scenario_id == scenario_id,
            models.CallTarget.phone_number == phone
        ).first()
        
        if not existing:
            new_target = models.CallTarget(
                scenario_id=scenario_id,
                phone_number=phone,
                metadata_json=json.dumps(row)
            )
            db.add(new_target)
            targets_added += 1
            
    db.commit()
    return {"message": f"{targets_added} targets added"}

@router.get("/scenarios/{scenario_id}/targets", response_model=List[schemas.CallTarget])
def read_targets(scenario_id: int, db: Session = Depends(get_db)):
    return db.query(models.CallTarget).filter(models.CallTarget.scenario_id == scenario_id).all()

@router.get("/scenarios/{scenario_id}/questions", response_model=List[schemas.Question])
def read_scenario_questions(scenario_id: int, db: Session = Depends(get_db)):
    return db.query(models.Question).filter(models.Question.scenario_id == scenario_id).order_by(models.Question.sort_order).all()

@router.get("/scenarios/{scenario_id}/ending_guidances", response_model=List[schemas.EndingGuidance])
def read_scenario_endings(scenario_id: int, db: Session = Depends(get_db)):
    return db.query(models.EndingGuidance).filter(models.EndingGuidance.scenario_id == scenario_id).order_by(models.EndingGuidance.sort_order).all()

@router.delete("/targets/{target_id}")
def delete_target(target_id: int, db: Session = Depends(get_db)):
    target = db.query(models.CallTarget).filter(models.CallTarget.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    db.delete(target)
    db.commit()
    return {"message": "Target deleted"}

@router.post("/scenarios/{scenario_id}/start_calls")
def start_calls(scenario_id: int, db: Session = Depends(get_db)):
    from twilio.rest import Client
    
    scenario = db.query(models.Scenario).get(scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    # Check working hours
    now = datetime.now() # System local time, should be JST in Railway if configured or handled
    # Simple check:
    current_time = now.strftime("%H:%M")
    if not (scenario.start_time <= current_time <= scenario.end_time):
        scenario.is_active = False # Auto OFF
        db.commit()
        raise HTTPException(status_code=400, detail=f"時間外です({scenario.start_time}-{scenario.end_time})。稼働フラグをOFFにしました。")

    targets = db.query(models.CallTarget).filter(
        models.CallTarget.scenario_id == scenario_id,
        models.CallTarget.status == "pending"
    ).limit(10).all() # Process in batches or just trigger 10 for test
    
    if not targets:
        return {"message": "No pending targets found"}

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    base_url = os.getenv("PUBLIC_BASE_URL")
    from_number = os.getenv("TWILIO_FROM_NUMBER") # Need this in .env

    calls_triggered = 0
    for target in targets:

        try:
            client.calls.create(
                to=target.phone_number,
                from_=from_number,
                url=f"{base_url}/twilio/outbound_handler?scenario_id={scenario_id}",
                status_callback=f"{base_url}/twilio/status_callback",
                status_callback_event=['initiated', 'ringing', 'answered', 'completed']
            )
            target.status = "calling"
            calls_triggered += 1
        except Exception as e:
            print(f"Failed to trigger call for {target.phone_number}: {e}")
            target.status = "failed"
            
    db.commit()
    return {"message": f"{calls_triggered} calls initiated"}

@router.post("/scenarios/{scenario_id}/stop")
def stop_scenario(scenario_id: int, mode: str = "soft", db: Session = Depends(get_db)):
    db_scenario = db.query(models.Scenario).get(scenario_id)
    if not db_scenario:
         raise HTTPException(status_code=404, detail="Scenario not found")
    
    if mode == "hard":
        db_scenario.is_hard_stopped = True
        db_scenario.is_active = False
    else:
        db_scenario.is_active = False
    db.commit()
    return {"message": f"Scenario stopped ({mode})"}

@router.post("/scenarios/{scenario_id}/stop_all")
def stop_all_calls(scenario_id: int, db: Session = Depends(get_db)):
    targets = db.query(models.CallTarget).filter(
        models.CallTarget.scenario_id == scenario_id,
        models.CallTarget.status.in_(["pending", "calling"])
    ).all()
    
    for t in targets:
        t.status = "failed" # or specialized status like 'canceled'
        
    db.commit()
    return {"message": f"{len(targets)} calls stopped/canceled"}


# --- Remaining endpoints (Questions, etc) ---
# ... (keep existing or update)
# I'll keep them as they are but ensure they are still there in the final file.
import json

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

# --- Logs and Analysis ---
@router.get("/calls/", response_model=List[schemas.CallLog])
def read_calls(
    skip: int = 0, 
    limit: int = 100, 
    to_number: Optional[str] = None, 
    from_number: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    scenario_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.Call).options(
        joinedload(models.Call.answers).joinedload(models.Answer.question),
        joinedload(models.Call.scenario),
        joinedload(models.Call.messages)
    )
    
    if scenario_id:
        query = query.filter(models.Call.scenario_id == scenario_id)
        
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
    import io
    import csv
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
    
    def format_domestic(phone):
        if not phone: return ""
        if phone.startswith("+81"): return "0" + phone[3:]
        return phone
        
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["CallSid", "Date", "To", "From", "ScenarioName", "Status", "Question", "AnswerType", "Transcript", "RecordingURL"])
    
    msg_stream = io.StringIO()
    msg_writer = csv.writer(msg_stream)
    msg_writer.writerow(["CallSid", "ScenarioName", "Date", "RecordingUrl", "Transcript", "RecordingSid"])
    
    for call in calls:
        scenario_name = call.scenario.name if call.scenario else "Unknown"
        date_str = call.started_at.strftime("%Y-%m-%d %H:%M:%S")
        to_dom = format_domestic(call.to_number)
        from_dom = format_domestic(call.from_number)
        
        if not call.answers:
            writer.writerow([call.call_sid, date_str, to_dom, from_dom, scenario_name, call.status, "-", "-", "-", "-"])
        else:
            for ans in call.answers:
                q_text = ans.question.text if ans.question else "Unknown"
                writer.writerow([call.call_sid, date_str, to_dom, from_dom, scenario_name, call.status, q_text, ans.answer_type, ans.transcript_text or "", ans.recording_url_twilio or ""])
        
        for msg in call.messages:
             msg_writer.writerow([call.call_sid, scenario_name, date_str, msg.recording_url or "", msg.transcript_text or "", msg.recording_sid or ""])
                
    zip_buffer = io.BytesIO()
    with pyzipper.AESZipFile(zip_buffer, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(b"attendme")
        zf.setencryption(pyzipper.WZ_AES, nbits=256)
        today = datetime.now().strftime("%Y%m%d")
        zf.writestr(f"{today}_logs.csv", stream.getvalue())
        zf.writestr(f"{today}_messages.csv", msg_stream.getvalue())
        
    zip_buffer.seek(0)
    filename = f"logs_{datetime.now().strftime('%Y%m%d%H%M')}.zip"
    
    return StreamingResponse(zip_buffer, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={filename}"})

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
