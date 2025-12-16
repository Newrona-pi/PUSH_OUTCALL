from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# --- Scenario Schemas ---
class ScenarioBase(BaseModel):
    name: str
    greeting_text: str
    disclaimer_text: Optional[str] = None
    is_active: bool = True

class ScenarioCreate(ScenarioBase):
    pass

class Scenario(ScenarioBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
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
    transcript_text: Optional[str]
    created_at: datetime

class CallLog(BaseModel):
    call_sid: str
    from_number: str
    to_number: str
    scenario_id: Optional[int]
    status: str
    started_at: datetime
    answers: List[AnswerLog] = []

    class Config:
        orm_mode = True
