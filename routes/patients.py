from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session as DBSession

from database import get_db
from models import Patient, Session, FlaggedWord
from schemas import PatientCreate, PatientOut

router = APIRouter(prefix="/api", tags=["patients"])


@router.get("/patients", response_model=list[PatientOut])
def list_patients(db: DBSession = Depends(get_db)):
    patients = db.query(Patient).all()
    return [patient_out(p, db) for p in patients]


@router.post("/patients", response_model=PatientOut)
def create_patient(data: PatientCreate, db: DBSession = Depends(get_db)):
    p = Patient(name=data.name.strip())
    db.add(p)
    db.commit()
    db.refresh(p)
    return patient_out(p, db)


@router.get("/patients/{patient_id}", response_model=PatientOut)
def get_patient(patient_id: int, db: DBSession = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if not p:
        raise HTTPException(404, "Patient not found")
    return patient_out(p, db)


def patient_out(p: Patient, db: DBSession) -> PatientOut:
    sessions = db.query(Session).filter(Session.patient_id == p.id).all()
    avg_comp = None
    if sessions:
        avg_comp = round(sum(s.comprehension_score for s in sessions) / len(sessions), 1)
    flagged = db.query(FlaggedWord).filter(FlaggedWord.patient_id == p.id).all()
    fc = {}
    for f in flagged:
        fc[f.word] = fc.get(f.word, 0) + 1
    top = sorted(fc, key=fc.get, reverse=True)[:3]
    return PatientOut(
        id=p.id,
        name=p.name,
        session_count=len(sessions),
        avg_comprehension=avg_comp,
        recommended_level=auto_level(sessions, flagged),
        top_flagged=top,
    )


def auto_level(sessions, flagged) -> int:
    if not sessions:
        return 3
    recent = sessions[-3:]
    avg_comp = sum(s.comprehension_score for s in recent) / len(recent)
    avg_flagged = sum(s.flagged_word_count for s in recent) / len(recent)
    avg_self = sum(s.self_understanding for s in recent) / len(recent)
    if avg_comp < 50 or avg_flagged > 6 or avg_self < 1.7:
        return 1
    if avg_comp < 65 or avg_flagged > 3.5 or avg_self < 2.2:
        return 2
    if avg_comp >= 88 and avg_flagged < 0.5 and avg_self >= 3.5:
        return 5
    if avg_comp >= 78 and avg_flagged < 1:
        return 4
    return 3
