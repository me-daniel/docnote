from pydantic import BaseModel
from typing import Optional


# ── Patient schemas ──

class PatientCreate(BaseModel):
    name: str

class PatientOut(BaseModel):
    id: int
    name: str
    session_count: int
    avg_comprehension: Optional[float]
    recommended_level: int
    top_flagged: list[str]


# ── Session schemas ──

class SessionCreate(BaseModel):
    patient_id: int
    comprehension_score: int
    read_time_seconds: int
    self_understanding: int          # 1-4
    difficulty_level: int            # 1-5
    flagged_words: list[str]
    word_frequencies: dict           # word -> count of hard words in text
    hover_times: dict                # word -> ms hovered

class SessionOut(BaseModel):
    id: int
    patient_id: int
    date: str
    comprehension_score: int
    read_time_seconds: int
    self_understanding: int
    difficulty_level: int
    flagged_word_count: int


# ── AI schemas ──

class SimplifyRequest(BaseModel):
    text: str
    difficulty_level: int           # 1-5
    patient_id: Optional[int] = None

class SimplifyResponse(BaseModel):
    simplified: str
    grade_level: float
    hard_word_pct: int

class SimilarityRequest(BaseModel):
    original: str
    simplified: str

class DefinitionRequest(BaseModel):
    word: str

class InsightRequest(BaseModel):
    patient_id: int
