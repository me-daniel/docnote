import json

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session as DBSession

from database import get_db
from models import Patient, Session, FlaggedWord
from schemas import SessionCreate, SessionOut

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/sessions", response_model=SessionOut)
def create_session(data: SessionCreate, db: DBSession = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == data.patient_id).first()
    if not p:
        raise HTTPException(404, "Patient not found")

    s = Session(
        patient_id=data.patient_id,
        comprehension_score=data.comprehension_score,
        read_time_seconds=data.read_time_seconds,
        self_understanding=data.self_understanding,
        difficulty_level=data.difficulty_level,
        flagged_word_count=len(data.flagged_words),
        word_frequencies=json.dumps(data.word_frequencies),
        hover_times=json.dumps(data.hover_times),
    )
    db.add(s)
    db.flush()

    for word in data.flagged_words:
        fw = FlaggedWord(patient_id=data.patient_id, session_id=s.id, word=word.lower())
        db.add(fw)

    db.commit()
    db.refresh(s)
    return session_out(s)


@router.get("/patients/{patient_id}/sessions", response_model=list[SessionOut])
def get_sessions(patient_id: int, db: DBSession = Depends(get_db)):
    sessions = db.query(Session).filter(Session.patient_id == patient_id).order_by(Session.id).all()
    return [session_out(s) for s in sessions]


def session_out(s: Session) -> SessionOut:
    return SessionOut(
        id=s.id,
        patient_id=s.patient_id,
        date=s.created_at.strftime("%d/%m/%Y") if s.created_at else "—",
        comprehension_score=s.comprehension_score,
        read_time_seconds=s.read_time_seconds,
        self_understanding=s.self_understanding,
        difficulty_level=s.difficulty_level,
        flagged_word_count=s.flagged_word_count,
    )
