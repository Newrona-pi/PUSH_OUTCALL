import os
import json
import base64
import asyncio
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from ..database import SessionLocal
from .. import models
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/realtime",
    tags=["realtime"],
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VOICE = "shimmer" # ユーザー指定がないので適当なものを選択（alloy, echo, shimmer）

# Realtime API URL
REALTIME_API_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"

@router.websocket("/stream/{call_sid}")
async def handle_media_stream(websocket: WebSocket, call_sid: str):
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for call: {call_sid}")

    db = SessionLocal()
    call = db.query(models.Call).filter(models.Call.call_sid == call_sid).first()
    if not call or not call.scenario:
        logger.error(f"Call or Scenario not found for SID: {call_sid}")
        await websocket.close()
        db.close()
        return

    scenario = call.scenario
    questions = db.query(models.Question).filter(
        models.Question.scenario_id == scenario.id,
        models.Question.is_active == True
    ).order_by(models.Question.sort_order).all()
    
    db.close()

    # Shared state
    state = {
        "current_question_index": 0,
        "questions": [q.text for q in questions],
        "mode": scenario.conversation_mode,
        "last_user_audio_time": asyncio.get_event_loop().time(),
        "silence_count": 0,
        "is_bridging": False,
        "stream_sid": None
    }

    async with websockets.connect(
        REALTIME_API_URL,
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=2024-10-01"
        }
    ) as openai_ws:
        
        # Initialize OpenAI Session
        await initialize_openai_session(openai_ws, scenario)

        # First prompt (Greeting)
        await send_initial_greeting(openai_ws, scenario, state)

        async def receive_from_twilio():
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data['event'] == 'media':
                        if not state["is_bridging"]:
                            # Forward audio to OpenAI
                            audio_payload = {
                                "type": "input_audio_buffer.append",
                                "audio": data['media']['payload']
                            }
                            await openai_ws.send(json.dumps(audio_payload))
                            # Update silence timer
                            state["last_user_audio_time"] = asyncio.get_event_loop().time()
                    
                    elif data['event'] == 'start':
                        state["stream_sid"] = data['start']['streamSid']
                        logger.info(f"Stream started: {state['stream_sid']}")
                    
                    elif data['event'] == 'stop':
                        logger.info("Twilio stream stopped")
                        break
            except WebSocketDisconnect:
                logger.info("Twilio WebSocket disconnected")
            except Exception as e:
                logger.error(f"Error in receive_from_twilio: {e}")

        async def receive_from_openai():
            try:
                async for message in openai_ws:
                    response = json.loads(message)
                    
                    if response["type"] == "response.audio.delta":
                        # Send audio back to Twilio
                        audio_data = {
                            "event": "media",
                            "streamSid": state["stream_sid"],
                            "media": {
                                "payload": response["audio"]
                            }
                        }
                        await websocket.send_json(audio_data)
                    
                    elif response["type"] == "response.done":
                        # Post-processing after AI finishes speaking
                        await handle_ai_response_done(openai_ws, response, state, call_sid)

                    elif response["type"] == "input_audio_buffer.speech_started":
                        # User started speaking, maybe interrupt AI (Twilio doesn't easily support interruption via clear, but we can try)
                        logger.info("User speech detected")
                        # Twilio 'clear' event helps clear the buffer
                        await websocket.send_json({"event": "clear", "streamSid": state["stream_sid"]})
                        # Also tell OpenAI to cancel current response
                        await openai_ws.send(json.dumps({"type": "response.cancel"}))

            except Exception as e:
                logger.error(f"Error in receive_from_openai: {e}")

        async def silence_monitor():
            while not state["is_bridging"]:
                await asyncio.sleep(1)
                now = asyncio.get_event_loop().time()
                elapsed = now - state["last_user_audio_time"]

                if elapsed > scenario.silence_timeout_short:
                    # User is silent for 15s
                    state["silence_count"] += 1
                    if elapsed > scenario.silence_timeout_long:
                        # 60s silence -> Hang up
                        logger.info(f"Silence timeout (60s) for {call_sid}")
                        await websocket.send_json({"event": "stop", "streamSid": state["stream_sid"]})
                        # Need to trigger actual hangup via Twilio REST API if possible, or just close WS
                        await websocket.close()
                        break
                    
                    # Remind user
                    if state["silence_count"] % 15 == 0: # Approx 15s since last check
                         await openai_ws.send(json.dumps({
                             "type": "response.create",
                             "response": {
                                 "instructions": "ユーザーの返答がありません。聞き取れなかった旨を伝え、回答を促してください。"
                             }
                         }))

        await asyncio.gather(receive_from_twilio(), receive_from_openai(), silence_monitor())

async def initialize_openai_session(openai_ws, scenario):
    instructions = f"""
あなたはオートコールシステムのAIアシスタントです。
シナリオ名: {scenario.name}
モード: {scenario.conversation_mode} (A: 質問順守, B: 自由対話, C: ハイブリッド)

基本ルール:
- 日本語で話してください。
- 親切かつ丁寧に対応してください。
- シナリオに従って進行してください。

モードA（質問順守）の場合:
- 決められた質問を1つずつ順番に聞いてください。
- ユーザーが脱線しても、優しく元の質問に戻してください。
- 全ての質問が済んだら、終話ガイダンスへ進んでください。

特定のキーワードへの対応:
- ユーザーが「興味がある」「詳しく聞きたい」「担当者と話したい」と言った場合、ブリッジ（担当者へ転送）を提案してください。
- ユーザーが「資料が欲しい」と言った場合、SMSでの資料送付を提案してください。

ブリッジの実行:
- ブリッジが必要な場合、関数 `trigger_bridge` を呼び出してください。
SMSの実行:
- SMS送付が必要な場合、関数 `trigger_sms` を呼び出してください。
"""
    
    session_update = {
        "type": "session.update",
        "session": {
            "instructions": instructions,
            "voice": VOICE,
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "tools": [
                {
                    "type": "function",
                    "name": "trigger_bridge",
                    "description": "担当者に電話を転送します。ユーザーの苗字（名前）を確認した後に呼び出してください。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "user_name": {"type": "string", "description": "ユーザーの苗字"}
                        },
                        "required": ["user_name"]
                    }
                },
                {
                    "type": "function",
                    "name": "trigger_sms",
                    "description": "資料送付のSMSを送信します。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {"type": "string", "description": "送付理由"}
                        }
                    }
                }
            ],
            "tool_choice": "auto"
        }
    }
    await openai_ws.send(json.dumps(session_update))

async def send_initial_greeting(openai_ws, scenario, state):
    greeting = f"{scenario.greeting_text or ''} {scenario.disclaimer_text or ''} {scenario.question_guidance_text or ''}"
    if state["questions"]:
        greeting += f" 最初の質問です。{state['questions'][0]}"
    
    await openai_ws.send(json.dumps({
        "type": "response.create",
        "response": {
            "instructions": f"以下の挨拶から開始してください: {greeting}"
        }
    }))

async def handle_ai_response_done(openai_ws, response, state, call_sid):
    # Check for tool calls
    output = response.get("response", {}).get("output", [])
    for item in output:
        if item.get("type") == "function_call":
            func_name = item["name"]
            args = json.loads(item["arguments"])
            
            if func_name == "trigger_bridge":
                logger.info(f"Triggering bridge for {call_sid} to user {args.get('user_name')}")
                state["is_bridging"] = True
                # Here we need to update Call record and trigger Dial
                await execute_bridge(call_sid, args.get("user_name"))
            
            elif func_name == "trigger_sms":
                logger.info(f"Triggering SMS for {call_sid}")
                await execute_sms_log(call_sid)

async def execute_bridge(call_sid, user_name):
    # This involves Twilio REST API to redirect the call to a TwiML that <Dial>s
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    from twilio.rest import Client
    
    db = SessionLocal()
    call = db.query(models.Call).filter(models.Call.call_sid == call_sid).first()
    if call and call.scenario and call.scenario.bridge_number:
        call.bridge_executed = True
        call.classification = "担当者に繋いだ"
        db.commit()
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        # Redirect the call to bridge endpoint
        bridge_url = f"{os.getenv('PUBLIC_BASE_URL')}/twilio/bridge_twiml?number={call.scenario.bridge_number}"
        client.calls(call_sid).update(url=bridge_url)
    db.close()

async def execute_sms_log(call_sid):
    db = SessionLocal()
    call = db.query(models.Call).filter(models.Call.call_sid == call_sid).first()
    if call:
        call.sms_sent_log = True
        db.commit()
    db.close()
