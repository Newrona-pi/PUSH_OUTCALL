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
VOICE = "shimmer" #alloy, echo, shimmer, ash, ballad, coral, sage,verse

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
                                audio_payload = {
                                    "type": "input_audio_buffer.append",
                                    "audio": data['media']['payload']
                                }
                                await openai_ws.send(json.dumps(audio_payload))
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
                        event_type = response.get("type")
                        
                        if event_type == "response.audio.delta":
                            # OpenAI sends audio in the 'delta' field, not 'audio'
                            audio_delta = response.get("delta")
                            if audio_delta and state["stream_sid"]:
                                audio_data = {
                                    "event": "media",
                                    "streamSid": state["stream_sid"],
                                    "media": {
                                        "payload": audio_delta
                                    }
                                }
                                await websocket.send_json(audio_data)
                            elif not audio_delta:
                                logger.warning(f"response.audio.delta event but no 'delta' field. Full response: {response}")
                        
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
                        
                        if int(elapsed) % 15 == 0:
                             await openai_ws.send(json.dumps({
                                 "type": "response.create",
                                 "response": {
                                     "instructions": "繝ｦ繝ｼ繧ｶ繝ｼ縺ｮ霑皮ｭ斐′荳螳壽凾髢薙≠繧翫∪縺帙ｓ縲り◇縺榊叙繧後↑縺九▲縺滓葎繧偵ｄ縺輔＠縺丈ｼ昴∴縲∝屓遲斐ｒ菫・＠縺ｦ縺上□縺輔＞縲・
                                 }
                             }))

            await asyncio.gather(receive_from_twilio(), receive_from_openai(), silence_monitor())
    except Exception as e:
        logger.exception(f"CRITICAL ERROR in handle_media_stream: {e}")
    finally:
        db.close()

async def initialize_openai_session(openai_ws, scenario):
    instructions = f"""
縺ゅ↑縺溘・繧ｪ繝ｼ繝医さ繝ｼ繝ｫ繧ｷ繧ｹ繝・Β縺ｮAI繧｢繧ｷ繧ｹ繧ｿ繝ｳ繝医〒縺吶・繧ｷ繝翫Μ繧ｪ蜷・ {scenario.name}
繝｢繝ｼ繝・ {scenario.conversation_mode} (A: 雉ｪ蝠城・ｮ・ C: 閾ｨ讖溷ｿ懷､会ｼ亥ｿ懃畑蝙具ｼ・

蝓ｺ譛ｬ繝ｫ繝ｼ繝ｫ:
- 譌･譛ｬ隱槭〒縲∵・繧九￥荳∝ｯｧ縺ｪ繝医・繝ｳ縺ｧ隧ｱ縺励※縺上□縺輔＞縲・- 繝ｦ繝ｼ繧ｶ繝ｼ縺ｮ隧ｱ繧帝・繧峨★縲∵怙蠕後∪縺ｧ閨槭＞縺ｦ縺九ｉ蠢懃ｭ斐＠縺ｦ縺上□縺輔＞縲・- 譌･莉倥ｒ閨槭＞縺溘ｉ蠢・★蠕ｩ蜚ｱ縺励※遒ｺ隱阪＠縺ｦ縺上□縺輔＞縲・- 縲梧・譌･縲阪梧・蠕梧律縲阪↑縺ｩ縺ｮ逶ｸ蟇ｾ逧・↑譌･莉倥・縲∝ｿ・★ `calculate_date` 繝・・繝ｫ繧剃ｽｿ縺｣縺ｦ迚ｹ螳壹＠縺ｦ縺上□縺輔＞縲・
縲蝉ｼ夊ｩｱ縺ｮ騾ｲ繧∵婿縲・1. 謖ｨ諡ｶ繧定｡後＞縲・夊ｩｱ縺ｮ逶ｮ逧・ｒ莨昴∴縺ｾ縺吶・2. 雉ｪ蝠上Μ繧ｹ繝医↓縺ゅｋ蜀・ｮｹ繧帝・分縺ｫ閨槭″蜃ｺ縺励∪縺吶・3. 繝ｦ繝ｼ繧ｶ繝ｼ縺瑚┳邱壹＠縺ｦ繧ゅ∝━縺励￥蜈・・雉ｪ蝠上Λ繧､繝ｳ縺ｫ謌ｻ縺励※縺上□縺輔＞縲・4. 蜈ｨ縺ｦ縺ｮ繧・ｊ蜿悶ｊ縺悟ｮ御ｺ・＠縺溘ｉ縲∫ｵりｩｱ繧ｬ繧､繝繝ｳ繧ｹ繧定ｪｭ縺ｿ荳翫￡縲～end_call` 繧貞他縺ｳ蜃ｺ縺励※邨ゆｺ・＠縺ｦ縺上□縺輔＞縲・
縲千音蛻･縺ｪ蟇ｾ蠢懊・- 縲梧球蠖楢・→隧ｱ縺励◆縺・阪瑚ｩｳ縺励￥閨槭″縺溘＞縲咲ｭ峨・隕∵悍縺後≠繧後・ `trigger_bridge` 繧貞ｮ溯｡後・- 雉・侭騾∽ｻ倥・蟶梧悍縺後≠繧後・ `trigger_sms` 繧貞ｮ溯｡後・"""
    
    session_update = {
        "type": "session.update",
        "session": {
            "instructions": instructions,
            "voice": VOICE,
            "modalities": ["text", "audio"],
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "turn_detection": None,
            "tools": [
                {
                    "type": "function",
                    "name": "calculate_date",
                    "description": "逶ｸ蟇ｾ逧・↑譌･莉倩｡ｨ迴ｾ・域・譌･縲∵擂騾ｱ縺ｪ縺ｩ・峨ｒ蜈ｷ菴鍋噪縺ｪ譌･莉倥↓螟画鋤縺励∪縺吶・,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "relative_expression": {"type": "string", "description": "逶ｸ蟇ｾ逧・↑陦ｨ迴ｾ・井ｾ具ｼ壽・譌･縲・譌･蠕鯉ｼ・}
                        },
                        "required": ["relative_expression"]
                    }
                },
                {
                    "type": "function",
                    "name": "trigger_bridge",
                    "description": "諡・ｽ楢・↓髮ｻ隧ｱ繧定ｻ｢騾√＠縺ｾ縺吶ゅΘ繝ｼ繧ｶ繝ｼ縺ｮ謇ｿ隲ｾ繧貞ｾ励◆蠕後↓螳溯｡後＠縺ｦ縺上□縺輔＞縲・,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "user_name": {"type": "string", "description": "繝ｦ繝ｼ繧ｶ繝ｼ縺ｮ蜷榊燕・亥・縺九ｌ縺ｰ・・}
                        }
                    }
                },
                {
                    "type": "function",
                    "name": "trigger_sms",
                    "description": "雉・侭騾∽ｻ倥・SMS繧帝∽ｿ｡縺励∪縺吶・,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {"type": "string", "description": "騾∽ｻ倡炊逕ｱ"}
                        }
                    }
                },
                {
                    "type": "function",
                    "name": "end_call",
                    "description": "騾夊ｩｱ繧堤ｵゆｺ・＠縺ｾ縺吶よ怙蠕後・謖ｨ諡ｶ繧堤ｵゅ∴縺溽峩蠕後↓蜻ｼ縺ｳ蜃ｺ縺励※縺上□縺輔＞縲・,
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
        greeting += f" 譛蛻昴・雉ｪ蝠上〒縺吶・state['questions'][0]}"
    
    await openai_ws.send(json.dumps({
        "type": "response.create",
        "response": {
            "instructions": f"莉･荳九・蜀・ｮｹ縺ｧ騾夊ｩｱ繧帝幕蟋九＠縺ｦ縺上□縺輔＞: {greeting}"
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
        
        if "譏取律" in rel: result_date = today + timedelta(days=1)
        elif "譏主ｾ梧律" in rel: result_date = today + timedelta(days=2)
        elif "譚･騾ｱ" in rel: result_date = today + timedelta(days=7)
        # Add more if needed...
        
        if result_date:
            date_str = result_date.strftime("%Y-%m-%d")
            output = f"{date_str} (邂怜・邨先棡)"
        else:
            output = "譌･莉倥・迚ｹ螳壹↓螟ｱ謨励＠縺ｾ縺励◆縲りｩｳ邏ｰ繧堤｢ｺ隱阪＠縺ｦ縺上□縺輔＞縲・
            
    elif func_name == "trigger_bridge":
        state["is_bridging"] = True
        await execute_bridge(call_sid, args.get("user_name"))
        output = "諡・ｽ楢・∈縺ｮ霆｢騾√ｒ髢句ｧ九＠縺ｾ縺吶・
        
    elif func_name == "trigger_sms":
        await execute_sms_log(call_sid)
        output = "雉・侭騾∽ｻ假ｼ・MS・峨・莠育ｴ・ｒ螳御ｺ・＠縺ｾ縺励◆縲・
        
    elif func_name == "end_call":
        state["is_ending"] = True
        output = "騾夊ｩｱ繧堤ｵゆｺ・＠縺ｾ縺吶・

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
        call.classification = "諡・ｽ楢・↓郢九＞縺"
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

