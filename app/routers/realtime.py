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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VOICE = "shimmer" #alloy, echo, shimmer, ash, ballad, coral, sage,verse

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
    
    ending_guidances = db.query(models.EndingGuidance).filter(
        models.EndingGuidance.scenario_id == scenario.id
    ).order_by(models.EndingGuidance.sort_order).all()
    
    db.close()

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
                        await handle_ai_response_done(openai_ws, response, state, call_sid, websocket)

                    elif response["type"] == "input_audio_buffer.speech_started":
                        # User started speaking, interrupt AI
                        logger.info("User speech detected - Interrupting AI")
                        await websocket.send_json({"event": "clear", "streamSid": state["stream_sid"]})
                        await openai_ws.send(json.dumps({"type": "response.cancel"}))
                    
                    elif response["type"] == "response.function_call_arguments.done":
                        await handle_function_call(openai_ws, response, state, call_sid)

            except Exception as e:
                logger.error(f"Error in receive_from_openai: {e}")

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
                    
                    # Remind user every 15s of silence
                    if int(elapsed) % 15 == 0:
                         await openai_ws.send(json.dumps({
                             "type": "response.create",
                             "response": {
                                 "instructions": "ユーザーの返答が一定時間ありません。聞き取れなかった旨をやさしく伝え、回答を促してください。"
                             }
                         }))

        await asyncio.gather(receive_from_twilio(), receive_from_openai(), silence_monitor())

async def initialize_openai_session(openai_ws, scenario):
    instructions = f"""
あなたはオートコールシステムのAIアシスタントです。
シナリオ名: {scenario.name}
モード: {scenario.conversation_mode} (A: 質問順守, C: 臨機応変（応用型）)

基本ルール:
- 日本語で、明るく丁寧なトーンで話してください。
- ユーザーの話を遮らず、最後まで聞いてから応答してください。
- 日付を聞いたら必ず復唱して確認してください。
- 「明日」「明後日」などの相対的な日付は、必ず `calculate_date` ツールを使って特定してください。

【会話の進め方】
1. 挨拶を行い、通話の目的を伝えます。
2. 質問リストにある内容を順番に聞き出します。
3. ユーザーが脱線しても、優しく元の質問ラインに戻してください。
4. 全てのやり取りが完了したら、終話ガイダンスを読み上げ、`end_call` を呼び出して終了してください。

【特別な対応】
- 「担当者と話したい」「詳しく聞きたい」等の要望があれば `trigger_bridge` を実行。
- 資料送付の希望があれば `trigger_sms` を実行。
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
        # Add more if needed...
        
        if result_date:
            date_str = result_date.strftime("%Y-%m-%d")
            output = f"{date_str} (算出結果)"
        else:
            output = "日付の特定に失敗しました。詳細を確認してください。"
            
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

    # Send function result back to OpenAI
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
    # Check if end_call was triggered via function or logically
    if state["is_ending"]:
        logger.info(f"AI requested end_call for {call_sid}")
        await asyncio.sleep(1.5) # Wait for final audio to play
        await websocket.close()

async def execute_bridge(call_sid, user_name):
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
        from urllib.parse import urlparse
        parsed_base = urlparse(os.getenv("PUBLIC_BASE_URL", ""))
        base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
        bridge_url = f"{base_domain}/twilio/bridge_twiml?number={call.scenario.bridge_number}"
        client.calls(call_sid).update(url=bridge_url)
    db.close()

async def execute_sms_log(call_sid):
    db = SessionLocal()
    call = db.query(models.Call).filter(models.Call.call_sid == call_sid).first()
    if call:
        call.sms_sent_log = True
        db.commit()
    db.close()

