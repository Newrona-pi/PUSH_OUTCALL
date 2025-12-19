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
VOICE = "alloy"  # Stable male voice

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


async def safe_ws_send_json(ws: WebSocket, data: dict) -> bool:
    """
    Send JSON to Twilio websocket safely.
    Twilio may close first; in that case, just stop sending to avoid noisy stack traces.
    """
    try:
        await ws.send_json(data)
        return True
    except Exception:
        return False


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

            # Initialize OpenAI Session (STRICT)
            await initialize_openai_session(openai_ws, scenario, state)

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
                                        await safe_ws_send_json(websocket, {"event": "clear", "streamSid": state["stream_sid"]})
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
                                    "media": {"payload": audio_delta}
                                }
                                await safe_ws_send_json(websocket, audio_data)

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
                                await safe_ws_send_json(websocket, {"event": "clear", "streamSid": state["stream_sid"]})
                            await openai_ws.send(json.dumps({"type": "response.cancel"}))

                        elif event_type == "response.function_call_arguments.done":
                            await handle_function_call(openai_ws, response, state, call_sid)

                        elif event_type == "error":
                            logger.error(f"OpenAI Error: {response}")

                except Exception as e:
                    logger.error(f"Error in receive_from_openai: {e}")
                    logger.exception("Full traceback:")

            async def silence_monitor():
                """
                Silence handling:
                - 反応がない場合のリマインドは最大2回まで（ループ防止）
                - それでも無反応なら、礼儀的に終了
                """
                while not state["is_bridging"] and not state["is_ending"]:
                    await asyncio.sleep(1)
                    now = asyncio.get_event_loop().time()

                    # If Twilio already closed, stop monitoring
                    if websocket.client_state.name != "CONNECTED":
                        break

                    elapsed = now - state["last_user_audio_time"]

                    # Long silence -> close
                    if elapsed > scenario.silence_timeout_long:
                        logger.info(f"Silence timeout ({scenario.silence_timeout_long}s) for {call_sid}")
                        state["is_ending"] = True
                        try:
                            await websocket.close()
                        except Exception:
                            pass
                        break

                    # Short silence -> gentle nudge (at most twice)
                    if elapsed > scenario.silence_timeout_short and (now - state["last_nudge_time"] >= 15) and (not state["ai_speaking"]):
                        state["last_nudge_time"] = now
                        state["silence_count"] += 1

                        if state["silence_count"] == 1:
                            nudge = "お聞かせください。回答が終わったら『以上です』とお伝えください。"
                        elif state["silence_count"] == 2:
                            nudge = "お声が聞こえにくいようです。もう一度、ゆっくりお話しください。"
                        else:
                            # Too many nudges -> end politely
                            nudge = "反応が確認できないため、いったん失礼いたします。"
                            state["is_ending"] = True

                        await openai_ws.send(json.dumps({
                            "type": "response.create",
                            "response": {
                                "instructions": (
                                    "前置き（承知しました等）なしで、次の文章だけを短く読み上げてください。\n"
                                    f"{nudge}"
                                )
                            }
                        }))

                        if state["is_ending"]:
                            await asyncio.sleep(1.0)
                            try:
                                await websocket.close()
                            except Exception:
                                pass
                            break


            await asyncio.gather(receive_from_twilio(), receive_from_openai(), silence_monitor())
    except Exception as e:
        logger.exception(f"CRITICAL ERROR in handle_media_stream: {e}")
    finally:
        db.close()


async def initialize_openai_session(openai_ws, scenario, state):
    """
    Realtime session bootstrap.
    重要: ここで「前置き禁止」「質問ループ禁止」「終話の確実化」を強く縛る。
    """
    # Build explicit script for stability (less free-form = fewer hallucinated fillers)
    questions = state.get("questions", [])
    ending_texts = state.get("ending_texts", [])

    # NOTE: ここでの指示は「絶対に従うルール」を先に置く
    banned_phrases = [
        "承知しました", "かしこまりました", "了解しました", "承りました",
        "ご不明点ありますか", "他にご不明点はございますか", "何かご不明点はありますか"
    ]

    instructions = f"""
あなたは「一次面接の自動音声面接官」です。日本語のみで話します。

【絶対ルール（違反禁止）】
- 返答の冒頭に「承知しました／かしこまりました／了解しました／承りました」などの前置きを入れない。
- 「ご不明点ありますか？」系の締め言葉を言わない。
- 同じ質問（特に1問目）を“自分から”繰り返さない。繰り返すのは、ユーザーが「もう一度」など明示したときだけ。
- ユーザーが話していないのに、勝手に会話を進めない（独り言禁止）。
- 重要: 最後まで完了したら、終話ガイダンスを読み上げた“直後に”必ず end_call を実行する。

【話し方】
- 落ち着いた丁寧語。短く、明瞭に。
- 文章はそのまま読み上げる（余計な相槌や言い換えを入れない）。

【進行（面接モードA前提・安定動作）】
- 質問はリストの順番で1つずつ。
- ユーザーが回答し終えた合図は「以上です」。
- 「以上です」を聞いたら、次の質問に進む。
- 1問あたり最大180秒を想定。長い場合は一度だけ要点の確認をして先に進める。
- 残り3問になったら「残り3問です」と一度だけ告知。

【会社名の名乗り】
- 最初に「カブシキガイシャパインズです」と必ず名乗る。

【禁止フレーズ】（絶対に言わない）
- {", ".join(banned_phrases)}

【質問リスト】（この順番厳守）
{chr(10).join([f"{i+1}. {q}" for i, q in enumerate(questions)])}

【終話ガイダンス】（最後にこの順で読み上げる）
{chr(10).join([f"- {t}" for t in ending_texts])}
"""

    session_update = {
        "type": "session.update",
        "session": {
            "instructions": instructions.strip(),
            "voice": VOICE,
            "modalities": ["text", "audio"],
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "turn_detection": {
                "type": "server_vad",
                # raise threshold to reduce echo false positives (tunable via ENV)
                "threshold": float(os.getenv("REALTIME_VAD_THRESHOLD", "0.7")),
                "prefix_padding_ms": int(os.getenv("REALTIME_VAD_PREFIX_MS", "500")),
                "silence_duration_ms": int(os.getenv("REALTIME_VAD_SILENCE_MS", "700")),
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
                    "parameters": {"type": "object", "properties": {}}
                }
            ],
            "tool_choice": "auto"
        }
    }
    await openai_ws.send(json.dumps(session_update))


async def send_initial_greeting(openai_ws, scenario, state):
    """
    重要: ここで「承知しました」等が出やすいので、"指示" ではなく "読み上げ" を強制する。
    """
    parts = [
        (scenario.greeting_text or "").strip(),
        (scenario.disclaimer_text or "").strip(),
        (scenario.question_guidance_text or "").strip(),
    ]
    greeting = " ".join([p for p in parts if p]).strip()

    if state.get("questions"):
        greeting = (greeting + " " if greeting else "") + f"最初の質問です。{state['questions'][0]}"

    # 「前置きなし」「そのまま読み上げ」を明示して、余計な返事を防ぐ
    await openai_ws.send(json.dumps({
        "type": "response.create",
        "response": {
            "instructions": (
                "次の文章を、前置き（例: 承知しました/かしこまりました/了解しました）なしで、"
                "一語一句なるべくそのまま読み上げてください。\n"
                f"---\n{greeting}\n---"
            )
        }
    }))


async def handle_function_call(openai_ws, response, state, call_sid):
    func_name = response["name"]
    call_id = response["call_id"]
    args = json.loads(response.get("arguments") or "{}")
    output = ""

    if func_name == "calculate_date":
        rel = args.get("relative_expression", "")
        jst = timezone(timedelta(hours=9))
        today = datetime.now(jst)
        result_date = None
        if "明日" in rel:
            result_date = today + timedelta(days=1)
        elif "明後日" in rel:
            result_date = today + timedelta(days=2)
        elif "来週" in rel:
            result_date = today + timedelta(days=7)

        if result_date:
            date_str = result_date.strftime("%Y-%m-%d")
            output = f"{date_str} (算出結果)"
        else:
            output = "日付の特定に失敗しました。"

    elif func_name == "trigger_bridge":
        state["is_bridging"] = True
        await execute_bridge(call_sid, args.get("user_name"))
        output = "担当者への転送を開始しました。"

    elif func_name == "trigger_sms":
        await execute_sms_log(call_sid)
        output = "SMS送付の処理を開始しました。"

    elif func_name == "end_call":
        # ここで response.create を出すと、余計な「承知しました」等が出たり、質問ループが起きやすい。
        state["is_ending"] = True
        output = "通話を終了します。"

    # Function call output back to OpenAI
    await openai_ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": output
        }
    }))

    # Only continue conversation when it is actually needed
    if func_name == "calculate_date":
        await openai_ws.send(json.dumps({
            "type": "response.create",
            "response": {
                "instructions": (
                    "前置きは不要です。算出した日付を短く復唱して確認し、会話を続けてください。"
                )
            }
        }))
    elif func_name in ("trigger_bridge", "trigger_sms"):
        # bridging/sms は Twilio 側ガイダンスがあるため、AIの追加発話は不要（ループ防止）
        return
    elif func_name == "end_call":
        return


async def handle_ai_response_done(openai_ws, response, state, call_sid, websocket):
    if state.get("is_ending"):
        logger.info(f"AI requested end_call for {call_sid}")
        await asyncio.sleep(1.0)
        try:
            await websocket.close()
        except Exception:
            pass


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
