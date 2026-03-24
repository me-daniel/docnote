from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

LEVEL_LABELS = {
    1: "Very Easy — Grade 3",
    2: "Easy — Grade 5",
    3: "Normal — Grade 7",
    4: "Advanced — Grade 9",
    5: "Complex — Clinical",
}

class Patient(Base):
    __tablename__ = "patients"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions      = relationship("Session",     back_populates="patient", cascade="all, delete")
    flagged_words = relationship("FlaggedWord", back_populates="patient", cascade="all, delete")


class Session(Base):
    __tablename__ = "sessions"

    id                  = Column(Integer, primary_key=True, index=True)
    patient_id          = Column(Integer, ForeignKey("patients.id"), nullable=False)
    comprehension_score = Column(Integer, default=0)      # 0-100
    read_time_seconds   = Column(Integer, default=0)
    self_understanding  = Column(Integer, default=0)      # 1-4
    difficulty_level    = Column(Integer, default=3)      # 1-5
    flagged_word_count  = Column(Integer, default=0)
    word_frequencies    = Column(Text, default="{}")      # JSON: word -> count
    hover_times         = Column(Text, default="{}")      # JSON: word -> ms
    created_at          = Column(DateTime, default=datetime.utcnow)

    patient       = relationship("Patient",     back_populates="sessions")
    flagged_words = relationship("FlaggedWord", back_populates="session", cascade="all, delete")


class FlaggedWord(Base):
    __tablename__ = "flagged_words"

    id         = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    word       = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="flagged_words")
    session = relationship("Session", back_populates="flagged_words")
