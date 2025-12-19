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

# --- Simple echo/barging-in mitigation knobs (tune as needed) ---
# When AI is speaking, we normally do NOT forward inbound audio to OpenAI.
# Allow barge-in only when inbound audio energy is clearly above threshold.
USER_BARGEIN_RMS_THRESHOLD = float(os.getenv("USER_BARGEIN_RMS_THRESHOLD", "1800"))
AI_SPEAKING_GUARD_MS = int(os.getenv("AI_SPEAKING_GUARD_MS", "200"))
# After AI finishes speaking, suppress inbound audio briefly to avoid echo triggering VAD
AI_POST_SPEAKING_SUPPRESS_MS = int(os.getenv("AI_POST_SPEAKING_SUPPRESS_MS", "900"))

# μ-law decode table (256)->PCM-ish int
def _ulaw_to_pcm(u: int) -> int:
    u = ~u & 0xFF
    sign = u & 0x80
    exponent = (u >> 4) & 0x07
    mantissa = u & 0x0F
    magnitude = ((mantissa << 1) + 1) << (exponent + 2)
    return -magnitude if sign else magnitude

_ULAW_TABLE = [_ulaw_to_pcm(i) for i in range(256)]

def _rms_ulaw(payload_b64: str) -> float:
    """Compute rough RMS from μ-law bytes (base64). Cheap & good enough for barge-in gating."""
    try:
        raw = base64.b64decode(payload_b64)
        if not raw:
            return 0.0
        s = 0
        step = 2  # reduce cost
        count = 0
        for b in raw[::step]:
            v = _ULAW_TABLE[b]
            s += v * v
            count += 1
        return (s / max(count, 1)) ** 0.5
    except Exception:
        return 0.0

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
            "stream_sid": None,
            # new for echo/loop mitigation
            "ai_speaking": False,
            "last_ai_audio_time": 0.0,
            "last_ai_audio_done_time": 0.0,
            "barge_in_armed": False,
            "last_nudge_time": 0.0
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
            
            # Initialize OpenAI Session
            await initialize_openai_session(openai_ws, scenario)

            # First prompt (Greeting)
            await send_initial_greeting(openai_ws, scenario, state)

            async def receive_from_twilio():
                try:
                    async for message in websocket.iter_text():
                        data = json.loads(message)
                        if data['event'] == 'media':
                            # Optional track filter (if Twilio provides it)
                            track = data.get("media", {}).get("track")
                            if track and track != "inbound":
                                continue

                            if not state["is_bridging"]:
                                payload = data['media']['payload']
                                now = asyncio.get_event_loop().time()

                                # Suppress immediate post-speech echo/noise right after AI finished speaking
                                if state["last_ai_audio_done_time"] and (now - state["last_ai_audio_done_time"]) * 1000 < AI_POST_SPEAKING_SUPPRESS_MS:
                                    continue

                                # If AI is speaking, do NOT forward audio by default to avoid echo-loop.
                                # Allow barge-in only when energy is clearly above threshold.
                                if state["ai_speaking"]:
                                    if (now - state["last_ai_audio_time"]) * 1000 < AI_SPEAKING_GUARD_MS:
                                        continue

                                    rms = _rms_ulaw(payload)
                                    if rms < USER_BARGEIN_RMS_THRESHOLD:
                                        continue

                                    # Real user barge-in detected
                                    state["barge_in_armed"] = True
                                    logger.info(f"Barge-in detected (rms={rms:.0f}). Canceling AI.")
                                    if state["stream_sid"]:
                                        await websocket.send_json({"event": "clear", "streamSid": state["stream_sid"]})
                                    await openai_ws.send(json.dumps({"type": "response.cancel"}))
                                    state["ai_speaking"] = False

                                # Forward audio when not AI speaking (or after barge-in)
                                audio_payload = {"type": "input_audio_buffer.append", "audio": payload}
                                await openai_ws.send(json.dumps(audio_payload))
                                state["last_user_audio_time"] = now
                        
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
                        event_type = response.get("type")
                        
                        if event_type == "response.audio.delta":
                            # OpenAI sends audio in the 'delta' field, not 'audio'
                            audio_delta = response.get("delta")
                            if audio_delta and state["stream_sid"]:
                                state["ai_speaking"] = True
                                state["last_ai_audio_time"] = asyncio.get_event_loop().time()
                                audio_data = {
                                    "event": "media",
                                    "streamSid": state["stream_sid"],
                                    "media": {
                                        "payload": audio_delta
                                    }
                                }
                                await websocket.send_json(audio_data)
                        
                        elif event_type == "response.audio.done":
                            logger.info("AI finished speaking")
                            state["ai_speaking"] = False
                            state["barge_in_armed"] = False
                            state["last_ai_audio_done_time"] = asyncio.get_event_loop().time()
                        
                        elif event_type == "response.done":
                            await handle_ai_response_done(openai_ws, response, state, call_sid, websocket)

                        elif event_type == "input_audio_buffer.speech_started":
                            # IMPORTANT:
                            # speech_started is noisy on phone calls (echo). Use it ONLY to interrupt when AI is currently speaking.
                            if not state["ai_speaking"]:
                                logger.info("speech_started ignored (AI not speaking)")
                                continue
                            if not state["barge_in_armed"]:
                                logger.info("speech_started ignored (AI speaking but not armed; likely echo)")
                                continue
                            logger.info("User barge-in confirmed - canceling AI")
                            if state["stream_sid"]:
                                await websocket.send_json({"event": "clear", "streamSid": state["stream_sid"]})
                            await openai_ws.send(json.dumps({"type": "response.cancel"}))
                        
                        elif event_type == "response.function_call_arguments.done":
                            await handle_function_call(openai_ws, response, state, call_sid)
                        
                        elif event_type == "error":
                            logger.error(f"OpenAI Error: {response}")

                except Exception as e:
                    logger.error(f"Error in receive_from_openai: {e}")
                    logger.exception("Full traceback:")

            async def silence_monitor():
                while not state["is_bridging"] and not state["is_ending"]:
                    await asyncio.sleep(1)
                    now = asyncio.get_event_loop().time()
                    elapsed = now - state["last_user_audio_time"]

                    if elapsed > scenario.silence_timeout_short:
                        state["silence_count"] += 1
                        if elapsed > scenario.silence_timeout_long:
                            logger.info(f"Silence timeout (60s) for {call_sid}")
                            await websocket.close()
                            break
                        
                        # Avoid spamming response.create every second. Nudge at most once per 15s.
                        if now - state["last_nudge_time"] >= 15 and not state["ai_speaking"]:
                            state["last_nudge_time"] = now
                            await openai_ws.send(json.dumps({
                                "type": "response.create",
                                "response": {
                                    "instructions": "ユーザーの返答が一定時間ありません。聞き取れなかった旨をやさしく伝え、回答を促してください。"
                                }
                            }))

            await asyncio.gather(receive_from_twilio(), receive_from_openai(), silence_monitor())
    except Exception as e:
        logger.exception(f"CRITICAL ERROR in handle_media_stream: {e}")
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

【会話の進め方】
1. 挨拶を行い、通話の目的を伝えます。
2. 質問リストにある内容を順番に聞き出します。
3. すべてのやり取りが完了したら、終話ガイダンスを読み上げ、`end_call` を呼び出して終了してください。
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
                # raise threshold to reduce echo false positives (tunable via ENV)
                "threshold": float(os.getenv("REALTIME_VAD_THRESHOLD", "0.7")),
                "prefix_padding_ms": int(os.getenv("REALTIME_VAD_PREFIX_MS", "500")),
                "silence_duration_ms": int(os.getenv("REALTIME_VAD_SILENCE_MS", "700"))
            },
            "tools": [
                {
                    "type": "function",
                    "name": "calculate_date",
                    "description": "相対的な日付表現（明日、来週など）を具体的な日付に変換します。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "relative_expression": {"type": "string", "description": "相対的な表現（例：明日、3日後）"}
                        },
                        "required": ["relative_expression"]
                    }
                },
                {
                    "type": "function",
                    "name": "trigger_bridge",
                    "description": "担当者に電話を転送します。ユーザーの承諾を得た後に実行してください。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "user_name": {"type": "string", "description": "ユーザーの名前（分かれば）"}
                        }
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
                },
                {
                    "type": "function",
                    "name": "end_call",
                    "description": "通話を終了します。最後の挨拶を終えた直後に呼び出してください。",
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
            "instructions": f"以下の内容で通話を開始してください: {greeting}"
        }
    }))

async def handle_function_call(openai_ws, response, state, call_sid):
    func_name = response["name"]
    call_id = response["call_id"]
    args = json.loads(response["arguments"])
    output = ""
    
    if func_name == "calculate_date":
        rel = args.get("relative_expression", "")
        jst = timezone(timedelta(hours=9))
        today = datetime.now(jst)
        result_date = None
        if "明日" in rel: result_date = today + timedelta(days=1)
        elif "明後日" in rel: result_date = today + timedelta(days=2)
        elif "来週" in rel: result_date = today + timedelta(days=7)
        
        if result_date:
            date_str = result_date.strftime("%Y-%m-%d")
            output = f"{date_str} (算出結果)"
        else:
            output = "日付の特定に失敗しました。"
            
    elif func_name == "trigger_bridge":
        state["is_bridging"] = True
        await execute_bridge(call_sid, args.get("user_name"))
        output = "担当者への転送を開始します。"
        
    elif func_name == "trigger_sms":
        await execute_sms_log(call_sid)
        output = "資料送付（SMS）の予約を完了しました。"
        
    elif func_name == "end_call":
        state["is_ending"] = True
        output = "通話を終了します。"

    await openai_ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": output
        }
    }))
    await openai_ws.send(json.dumps({"type": "response.create"}))

async def handle_ai_response_done(openai_ws, response, state, call_sid, websocket):
    if state["is_ending"]:
        logger.info(f"AI requested end_call for {call_sid}")
        await asyncio.sleep(1.5)
        await websocket.close()

async def execute_bridge(call_sid, user_name):
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    from twilio.rest import Client
    db = SessionLocal()
    call = db.query(models.Call).filter(models.Call.call_sid == call_sid).first()
    if call and call.scenario and call.scenario.bridge_number:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        public_base = os.getenv("PUBLIC_BASE_URL", "").rstrip('/')
        url = f"{public_base}/twilio/bridge_twiml?number={call.scenario.bridge_number}"
        client.calls(call_sid).update(url=url)
        call.bridge_executed = True
        db.commit()
    db.close()

async def execute_sms_log(call_sid):
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    from twilio.rest import Client
    db = SessionLocal()
    call = db.query(models.Call).filter(models.Call.call_sid == call_sid).first()
    if call and call.scenario and call.scenario.sms_template:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=call.scenario.sms_template,
            from_=call.from_number,
            to=call.to_number
        )
        call.sms_sent_log = True
        db.commit()
    db.close()
