from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# --- EndingGuidance Schemas ---
class EndingGuidanceBase(BaseModel):
    text: str
    sort_order: int = 0

class EndingGuidanceCreate(EndingGuidanceBase):
    scenario_id: int

class EndingGuidance(EndingGuidanceBase):
    id: int
    scenario_id: int
    created_at: datetime
    
    class Config:
        orm_mode = True

# --- Scenario Schemas ---
class ScenarioBase(BaseModel):
    name: str
    greeting_text: str
    disclaimer_text: Optional[str] = None
    question_guidance_text: Optional[str] = None
    conversation_mode: str = "A"
    start_time: str = "10:00"
    end_time: str = "18:00"
    is_active: bool = True
    is_hard_stopped: bool = False
    silence_timeout_short: int = 15
    silence_timeout_long: int = 60
    bridge_number: Optional[str] = None
    sms_template: Optional[str] = None

class ScenarioCreate(ScenarioBase):
    pass

class Scenario(ScenarioBase):
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    ending_guidances: List[EndingGuidance] = []
    
    class Config:
        orm_mode = True

# --- Question Schemas ---
class QuestionBase(BaseModel):
    text: str
    sort_order: int = 0
    is_active: bool = True

class QuestionCreate(QuestionBase):
    scenario_id: int

class Question(QuestionBase):
    id: int
    scenario_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

# --- CallTarget Schemas ---
class CallTargetBase(BaseModel):
    phone_number: str
    scenario_id: int
    metadata_json: Optional[str] = None

class CallTargetCreate(CallTargetBase):
    pass

class CallTarget(CallTargetBase):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

# --- Blacklist Schemas ---
class BlacklistBase(BaseModel):
    phone_number: str
    reason: Optional[str] = None

class Blacklist(BlacklistBase):
    created_at: datetime

    class Config:
        orm_mode = True

# --- PhoneNumber Schemas ---
class PhoneNumberBase(BaseModel):
    to_number: str
    label: Optional[str] = None
    is_active: bool = True

class PhoneNumberCreate(PhoneNumberBase):
    scenario_id: int

class PhoneNumber(PhoneNumberBase):
    scenario_id: int
    
    class Config:
        orm_mode = True

# --- Call/Answer Schemas (for logging) ---
class AnswerLog(BaseModel):
    id: int
    question_text: Optional[str]
    recording_url_twilio: Optional[str]
    recording_sid: Optional[str]
    transcript_text: Optional[str]
    transcript_status: Optional[str]
    question_sort_at_call: Optional[int]
    created_at: datetime
    
    class Config:
        orm_mode = True

class MessageLog(BaseModel):
    id: int
    recording_url: Optional[str]
    transcript_text: Optional[str]
    created_at: datetime
    
    class Config:
        orm_mode = True

class CallLog(BaseModel):
    call_sid: str
    from_number: str
    to_number: str
    scenario_id: Optional[int]
    scenario_name: Optional[str] = None
    status: str
    direction: str
    classification: Optional[str] = None
    bridge_executed: bool = False
    sms_sent_log: bool = False
    transcript_full: Optional[str] = None
    recording_sid: Optional[str]
    started_at: datetime
    answers: List[AnswerLog] = []
    messages: List[MessageLog] = []

    class Config:
        orm_mode = True

