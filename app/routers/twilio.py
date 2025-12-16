from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from twilio.twiml.voice_response import VoiceResponse
from ..database import get_db
from .. import models

router = APIRouter(
    prefix="/twilio",
    tags=["twilio"],
)

@router.post("/voice")
async def handle_incoming_call(
    request: Request,
    To: str = Form(...),
    From: str = Form(...),
    CallSid: str = Form(...),
    db: Session = Depends(get_db)
):
    # Normalize phone number (remove spaces, hyphens, parentheses, and handle + prefix)
    def normalize_phone(number):
        # Remove common formatting characters
        normalized = number.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        # Ensure it starts with +
        if not normalized.startswith('+'):
            normalized = '+' + normalized
        return normalized
    
    to_normalized = normalize_phone(To)
    
    # 1. Look up Scenario by To number (try exact match first, then normalized)
    phone_entry = db.query(models.PhoneNumber).filter(models.PhoneNumber.to_number == To).first()
    if not phone_entry:
        # Try normalized lookup
        all_numbers = db.query(models.PhoneNumber).all()
        for pn in all_numbers:
            if normalize_phone(pn.to_number) == to_normalized:
                phone_entry = pn
                break
    
    # Create Call record
    call = models.Call(
        call_sid=CallSid,
        from_number=From,
        to_number=To,
        status="in-progress",
        scenario_id=phone_entry.scenario_id if phone_entry else None
    )
    db.add(call)
    db.commit()

    vr = VoiceResponse()

    if not phone_entry or not phone_entry.scenario.is_active:
        vr.say("現在この番号は使われておりません。", language="ja-JP")
        return Response(content=str(vr), media_type="application/xml")

    scenario = phone_entry.scenario

    # 2. Greeting
    if scenario.greeting_text:
        vr.say(scenario.greeting_text, language="ja-JP")
    
    if scenario.disclaimer_text:
        vr.say(scenario.disclaimer_text, language="ja-JP")

    # 3. Question Guidance (before first question)
    guidance_text = scenario.question_guidance_text or "このあと何点か質問をさせていただきます。回答が済みましたら＃を押して次に進んでください"
    vr.say(guidance_text, language="ja-JP")
    vr.pause(length=1.5)  # 1.5 second pause

    # 4. Ask First Question
    first_question = db.query(models.Question).filter(
        models.Question.scenario_id == scenario.id,
        models.Question.is_active == True
    ).order_by(models.Question.sort_order).first()

    if first_question:
        vr.say(first_question.text, language="ja-JP")
        action_url = f"/twilio/record_callback?scenario_id={scenario.id}&q_curr={first_question.id}"
        # Remove max_length, set timeout=0 to disable auto-end, enable transcription
        vr.record(
            action=action_url, 
            finish_on_key="#",
            timeout=0,  # Disable silence detection
            transcribe=True,  # Enable transcription
            transcribe_callback=f"/twilio/transcription_callback",
            transcribe_language="ja-JP"  # Japanese transcription
        )
    else:
        vr.say("質問が設定されていません。終了します。", language="ja-JP")

    return Response(content=str(vr), media_type="application/xml")

@router.post("/record_callback")
async def handle_recording(
    request: Request,
    scenario_id: int,
    q_curr: int, # The question ID that was just answered
    CallSid: str = Form(...),
    RecordingUrl: str = Form(...),
    RecordingSid: str = Form(...),
    db: Session = Depends(get_db)
):
    # 1. Save Answer
    answer = models.Answer(
        call_sid=CallSid,
        question_id=q_curr,
        answer_type="recording",
        recording_sid=RecordingSid,
        recording_url_twilio=RecordingUrl
    )
    db.add(answer)
    db.commit()

    vr = VoiceResponse()

    # 2. Find Next Question
    # Get current question to find sort_order
    current_q = db.query(models.Question).get(q_curr)
    if not current_q:
        vr.say("エラーが発生しました。", language="ja-JP")
        return Response(content=str(vr), media_type="application/xml")

    next_question = db.query(models.Question).filter(
        models.Question.scenario_id == scenario_id,
        models.Question.is_active == True,
        models.Question.sort_order > current_q.sort_order
    ).order_by(models.Question.sort_order).first()

    if next_question:
        # Ask next
        vr.say(next_question.text, language="ja-JP")
        action_url = f"/twilio/record_callback?scenario_id={scenario_id}&q_curr={next_question.id}"
        vr.record(
            action=action_url, 
            finish_on_key="#",
            timeout=0,
            transcribe=True,
            transcribe_callback=f"/twilio/transcription_callback",
            transcribe_language="ja-JP"
        )
    else:
        # No more questions
        vr.say("ご回答ありがとうございました。失礼いたします。", language="ja-JP")
        vr.hangup()

    return Response(content=str(vr), media_type="application/xml")

@router.post("/transcription_callback")
async def handle_transcription(
    request: Request,
    TranscriptionText: str = Form(None),
    RecordingSid: str = Form(...),
    db: Session = Depends(get_db)
):
    # Update answer with transcription
    answer = db.query(models.Answer).filter(models.Answer.recording_sid == RecordingSid).first()
    if answer:
        answer.transcript_text = TranscriptionText
        answer.transcript_status = "completed"
        db.commit()
    
    return Response(content="OK", media_type="text/plain")
