from datetime import datetime, timezone, timedelta
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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
VOICE = "alloy" # Stable male voice

# Realtime API URL
REALTIME_API_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime"

@router.websocket("/stream/{call_sid}")
async def handle_media_stream(websocket: WebSocket, call_sid: str):
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for call: {call_sid}")

    db = SessionLocal()
    try:
        call = db.query(models.Call).filter(models.Call.call_sid == call_sid).first()
        if not call or not call.scenario:
            logger.error(f"Call or Scenario not found for SID: {call_sid}")
            await websocket.close()
            return

        scenario = call.scenario
        questions = db.query(models.Question).filter(
            models.Question.scenario_id == scenario.id,
            models.Question.is_active == True
        ).order_by(models.Question.sort_order).all()
        
        ending_guidances = db.query(models.EndingGuidance).filter(
            models.EndingGuidance.scenario_id == scenario.id
        ).order_by(models.EndingGuidance.sort_order).all()
        
        # Shared state
        state = {
            "current_question_index": 0,
            "questions": [q.text for q in questions],
            "ending_texts": [e.text for e in ending_guidances],
            "mode": scenario.conversation_mode,
            "last_user_audio_time": asyncio.get_event_loop().time(),
            "silence_count": 0,
            "is_bridging": False,
            "is_ending": False,
            "session_updated": asyncio.Event(),
            "stream_sid": None
        }

        logger.info(f"Connecting to OpenAI Realtime API for call {call_sid}...")
        
        # Headers for OpenAI (Note: Newer 'websockets' v13+ uses 'additional_headers')
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        try:
            # Try both names to be compatible with different 'websockets' versions
            openai_conn = websockets.connect(
                REALTIME_API_URL,
                additional_headers=headers
            )
        except TypeError:
            openai_conn = websockets.connect(
                REALTIME_API_URL,
                extra_headers=headers
            )

        async with openai_conn as openai_ws:
            logger.info(f"Connected to OpenAI successfully for call {call_sid}")
            
            # 1. Initialize OpenAI Session
            await initialize_openai_session(openai_ws, scenario)
            
            async def receive_from_twilio():
                try:
                    async for message in websocket.iter_text():
                        data = json.loads(message)
                        if data['event'] == 'media':
                            # ONLY send audio AFTER session is fully configured
                            if not state["is_bridging"] and state["session_updated"].is_set():
                                await openai_ws.send(json.dumps({
                                    "type": "input_audio_buffer.append",
                                    "audio": data['media']['payload']
                                }))
                                state["last_user_audio_time"] = asyncio.get_event_loop().time()
                        
                        elif data['event'] == 'start':
                            state["stream_sid"] = data['start']['streamSid']
                            logger.info(f"Stream started: {state['stream_sid']}")
                        
                        elif data['event'] == 'dtmf':
                            digit = data.get('dtmf', {}).get('digit', '')
                            if digit == '#':
                                await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                                await openai_ws.send(json.dumps({"type": "response.create"}))
                        
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
                        event_type = response.get("type")
                        
                        if event_type == "response.audio.delta":
                            audio_delta = response.get("delta")
                            if audio_delta and state["stream_sid"]:
                                await websocket.send_json({
                                    "event": "media",
                                    "streamSid": state["stream_sid"],
                                    "media": {"payload": audio_delta}
                                })
                        
                        elif event_type == "session.updated":
                            logger.info("OpenAI session confirmed codec settings")
                            state["session_updated"].set()

                        elif event_type == "response.audio.done":
                            logger.info("AI finished speaking")
                        
                        elif event_type == "response.done":
                            await handle_ai_response_done(openai_ws, response, state, call_sid, websocket)

                        elif event_type == "input_audio_buffer.speech_started":
                            logger.info("User speech detected - Interrupting AI")
                            await websocket.send_json({"event": "clear", "streamSid": state["stream_sid"]})
                            await openai_ws.send(json.dumps({"type": "response.cancel"}))
                        
                        elif event_type == "response.function_call_arguments.done":
                            await handle_function_call(openai_ws, response, state, call_sid)
                        
                        elif event_type == "error":
                            logger.error(f"OpenAI Error: {response}")

                except Exception as e:
                    logger.error(f"Error in receive_from_openai: {e}")

            async def silence_monitor():
                while not state["is_bridging"] and not state["is_ending"]:
                    await asyncio.sleep(1)
                    now = asyncio.get_event_loop().time()
                    elapsed = now - state["last_user_audio_time"]
                    if elapsed > scenario.silence_timeout_short:
                        if elapsed > scenario.silence_timeout_long:
                            await websocket.close()
                            break
                        if int(elapsed) % 15 == 0:
                             await openai_ws.send(json.dumps({
                                 "type": "response.create",
                                 "response": {"instructions": "返答がないため、やさしく回答を促してください。"}
                             }))

            # Start background processors
            twilio_task = asyncio.create_task(receive_from_twilio())
            openai_task = asyncio.create_task(receive_from_openai())
            monitor_task = asyncio.create_task(silence_monitor())

            # 2. WAIT for synchronized session update (Crucial for g711_ulaw)
            try:
                await asyncio.wait_for(state["session_updated"].wait(), timeout=5.0)
                logger.info("Session confirmed - triggering greeting")
            except asyncio.TimeoutError:
                logger.warning("Session update sync timeout - codec might be wrong")

            # 3. Send initial greeting
            await send_initial_greeting(openai_ws, scenario, state)

            await asyncio.gather(twilio_task, openai_task, monitor_task)

    except Exception as e:
        logger.exception(f"CRITICAL ERROR: {e}")
    finally:
        db.close()

async def initialize_openai_session(openai_ws, scenario):
    instructions = f"""
あなたはオートコールシステムのAIアシスタントです。
シナリオ名: {scenario.name}
モード: {scenario.conversation_mode} (A: 質問順守, C: 臨機応変)

基本ルール:
- 日本語で、誠実で落ち着いた、丁寧な男性のトーンで話してください。
- ユーザーの話を遮らず、最後まで聞いてから応答してください。
- 日付を聞いたら必ず復唱して確認してください。
- 「明日」「明後日」などの相対的な日付は、必ず `calculate_date` ツールを使って特定してください。

【相槌・復唱について】
- 相槌は最小限にしてください。
- 回答を受けたら「○○ですね、承知しました」と簡潔に確認し、すぐ次の質問に進んでください。

【会話の進める手順】
1. 挨拶を行い、通話の目的を伝えます。
2. 質問リストの内容を順番に聞き出します。
3. すべて完了したら、終話ガイダンスを読み上げ `end_call` を呼び出します。
"""
    
    session_update = {
        "type": "session.update",
        "session": {
            "instructions": instructions,
            "voice": VOICE,
            "modalities": ["text", "audio"],
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 15000 
            },
            "tools": [
                {
                    "type": "function",
                    "name": "calculate_date",
                    "description": "日付特定用",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "relative_expression": {"type": "string"}
                        },
                        "required": ["relative_expression"]
                    }
                },
                {
                    "type": "function",
                    "name": "trigger_bridge",
                    "description": "転送用",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "user_name": {"type": "string"}
                        }
                    }
                },
                {
                    "type": "function",
                    "name": "trigger_sms",
                    "description": "SMS送信用",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {"type": "string"}
                        }
                    }
                },
                {
                    "type": "function",
                    "name": "end_call",
                    "description": "通話終了用",
                    "parameters": {
                        "type": "object",
                        "properties": {}
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
            "instructions": f"以下の内容で開始してください: {greeting}"
        }
    }))

async def handle_ai_response_done(openai_ws, response, state, call_sid, websocket):
    # Log or handle when a total response is done
    pass

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

async def handle_function_call(openai_ws, response, state, call_sid):
    func_name = response["name"]
    call_id = response["call_id"]
    args = json.loads(response["arguments"])
    output = ""
    
    if func_name == "calculate_date":
        output = "日付を特定しました。"
    elif func_name == "trigger_bridge":
        state["is_bridging"] = True
        await execute_bridge(call_sid, args.get("user_name"))
        output = "担当者への転送を開始します。"
    elif func_name == "trigger_sms":
        await execute_sms_log(call_sid)
        output = "資料送付（SMS）の予約を完了しました。"
    elif func_name == "end_call":
        state["is_ending"] = True
        output = "全ての質問が完了しました。通話を終了します。"

    await openai_ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": output
        }
    }))
    await openai_ws.send(json.dumps({"type": "response.create"}))

async def execute_bridge(call_sid, user_name):
    from twilio.rest import Client
    db = SessionLocal()
    try:
        call = db.query(models.Call).filter(models.Call.call_sid == call_sid).first()
        if call and call.scenario and call.scenario.bridge_number:
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            public_base = os.getenv("PUBLIC_BASE_URL", "").rstrip('/')
            url = f"{public_base}/twilio/bridge_twiml?number={call.scenario.bridge_number}"
            client.calls(call_sid).update(url=url)
            logger.info(f"Call bridged: {call_sid} -> {call.scenario.bridge_number}")
    except Exception as e:
        logger.error(f"Bridge error: {e}")
    finally:
        db.close()

async def execute_sms_log(call_sid):
    from twilio.rest import Client
    db = SessionLocal()
    try:
        call = db.query(models.Call).filter(models.Call.call_sid == call_sid).first()
        if call and call.scenario and call.scenario.sms_template:
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            # Use the number the call was made FROM (Twilio number)
            from_num = call.from_number 
            client.messages.create(
                body=call.scenario.sms_template,
                from_=from_num,
                to=call.to_number
            )
            logger.info(f"SMS sent to {call.to_number}")
    except Exception as e:
        logger.error(f"SMS error: {e}")
    finally:
        db.close()
