from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    greeting_text = Column(String) # 通話開始時の挨拶
    disclaimer_text = Column(String, nullable=True) # 録音告知など
    question_guidance_text = Column(String, nullable=True, default="このあと何点か質問をさせていただきます。回答が済みましたらシャープを押して次に進んでください") # 質問開始前のガイダンス
    
    # New fields for Outbound/GPT-Realtime
    conversation_mode = Column(String, default="A") # A: 質問順守, B: 自由対話, C: ハイブリッド
    start_time = Column(String, default="10:00")
    end_time = Column(String, default="18:00")
    is_active = Column(Boolean, default=True) # ソフト停止用
    is_hard_stopped = Column(Boolean, default=False) # ハード停止用
    
    silence_timeout_short = Column(Integer, default=15) # 15秒ごとのメッセージ
    silence_timeout_long = Column(Integer, default=60) # 60秒で切断
    
    bridge_number = Column(String, nullable=True) # 担当者番号
    sms_template = Column(Text, nullable=True) # SMSテンプレ
    
    deleted_at = Column(DateTime, nullable=True) # Soft delete functionality
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    phone_numbers = relationship("PhoneNumber", back_populates="scenario")
    questions = relationship("Question", back_populates="scenario")
    ending_guidances = relationship("EndingGuidance", back_populates="scenario", order_by="EndingGuidance.sort_order")
    targets = relationship("CallTarget", back_populates="scenario")

class EndingGuidance(Base):
    __tablename__ = "ending_guidances"
    
    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"))
    text = Column(String)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    scenario = relationship("Scenario", back_populates="ending_guidances")

class PhoneNumber(Base):
    __tablename__ = "phone_numbers"

    to_number = Column(String, primary_key=True) # E.164 format
    scenario_id = Column(Integer, ForeignKey("scenarios.id"))
    label = Column(String, nullable=True) # UIでは「備考」として表示
    is_active = Column(Boolean, default=True)

    scenario = relationship("Scenario", back_populates="phone_numbers")

class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"))
    text = Column(String)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    scenario = relationship("Scenario", back_populates="questions")

class CallTarget(Base):
    __tablename__ = "call_targets"
    
    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"))
    phone_number = Column(String, index=True)
    status = Column(String, default="pending") # pending, calling, completed, failed, opted_out
    metadata_json = Column(Text, nullable=True) # CSVの他カラムを保存
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    scenario = relationship("Scenario", back_populates="targets")


class Call(Base):
    __tablename__ = "calls"

    call_sid = Column(String, primary_key=True)
    from_number = Column(String, index=True)
    to_number = Column(String, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=True)
    status = Column(String) # queued, ringing, in-progress, completed, busy, failed, no-answer
    direction = Column(String, default="inbound") # inbound, outbound
    
    # Classification
    classification = Column(String, nullable=True) 
    # 「担当者に繋いだ」「聞いたが担当者まで進まなかった」「冒頭15秒以内切断」
    
    bridge_executed = Column(Boolean, default=False)
    sms_sent_log = Column(Boolean, default=False)
    
    transcript_full = Column(Text, nullable=True) # 高精度文字起こし
    
    duration = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    recording_sid = Column(String, nullable=True) # Full call recording SID

    answers = relationship("Answer", back_populates="call")
    messages = relationship("Message", back_populates="call")
    scenario = relationship("Scenario")
    
    @property
    def scenario_name(self):
        return self.scenario.name if self.scenario else None

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    call_sid = Column(String, ForeignKey("calls.call_sid"))
    recording_sid = Column(String, nullable=True)
    recording_url = Column(String, nullable=True)
    transcript_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    call = relationship("Call", back_populates="messages")

class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, index=True)
    call_sid = Column(String, ForeignKey("calls.call_sid"))
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=True)
    answer_type = Column(String, default="recording") # recording, dtmf, etc
    
    recording_sid = Column(String, nullable=True)
    recording_url_twilio = Column(String, nullable=True)
    
    # Storage
    storage_url = Column(String, nullable=True) 
    storage_status = Column(String, default="pending") 
    
    transcript_text = Column(Text, nullable=True)
    transcript_status = Column(String, default="pending")
    question_sort_at_call = Column(Integer, default=0) # Order snapshot
    
    created_at = Column(DateTime, default=datetime.utcnow)

    call = relationship("Call", back_populates="answers")
    question = relationship("Question")

    @property
    def question_text(self):
        return self.question.text if self.question else None

class TranscriptionLog(Base):
    __tablename__ = "transcription_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    answer_id = Column(Integer, ForeignKey("answers.id"), nullable=True)
    service = Column(String, default="openai_whisper")
    status = Column(String) # success, failed
    
    # Phase 2 Investigation Columns
    audio_bytes = Column(Integer, nullable=True)
    audio_duration = Column(Integer, nullable=True) # in seconds (float might be better but user said audio_duration_sec, integer is usually fine for logging)
    model_name = Column(String, nullable=True)
    language = Column(String, default="ja")
    
    request_payload = Column(Text, nullable=True)
    response_payload = Column(Text, nullable=True)
    processing_time = Column(Integer, default=0) # duration_sec renaming/alias
    
    created_at = Column(DateTime, default=datetime.utcnow)

