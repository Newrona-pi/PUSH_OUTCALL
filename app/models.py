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
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    phone_numbers = relationship("PhoneNumber", back_populates="scenario")
    questions = relationship("Question", back_populates="scenario")

class PhoneNumber(Base):
    __tablename__ = "phone_numbers"

    to_number = Column(String, primary_key=True) # E.164 format
    scenario_id = Column(Integer, ForeignKey("scenarios.id"))
    label = Column(String, nullable=True) # "Aさん専用", "キャンペーンA" etc
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

class Call(Base):
    __tablename__ = "calls"

    call_sid = Column(String, primary_key=True)
    from_number = Column(String, index=True)
    to_number = Column(String, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=True)
    status = Column(String) # queued, ringing, in-progress, completed, busy, failed, no-answer
    started_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    answers = relationship("Answer", back_populates="call")
    scenario = relationship("Scenario")
    
    @property
    def scenario_name(self):
        return self.scenario.name if self.scenario else None

class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, index=True)
    call_sid = Column(String, ForeignKey("calls.call_sid"))
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=True)
    answer_type = Column(String, default="recording") # recording, dtmf, etc
    
    recording_sid = Column(String, nullable=True)
    recording_url_twilio = Column(String, nullable=True)
    
    # 将来的な拡張用
    storage_url = Column(String, nullable=True) 
    storage_status = Column(String, default="pending") 
    
    transcript_text = Column(Text, nullable=True)
    transcript_status = Column(String, default="pending")
    
    created_at = Column(DateTime, default=datetime.utcnow)

    call = relationship("Call", back_populates="answers")
    question = relationship("Question")

    @property
    def question_text(self):
        return self.question.text if self.question else None
