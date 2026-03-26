import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, Patient, Session, FlaggedWord

DATABASE_URL = "sqlite:///./doctortalk.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}   # needed for SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _seed_uwe_demo():
    """Demo patient Uwe with sessions so Analytics has default charts."""
    db = SessionLocal()
    try:
        uwe = db.query(Patient).filter(Patient.name == "Uwe").first()
        if uwe:
            if db.query(Session).filter(Session.patient_id == uwe.id).count() > 0:
                return
        else:
            uwe = Patient(name="Uwe")
            db.add(uwe)
            db.commit()
            db.refresh(uwe)

        demos = [
            (62, 118, 2, 2, ["dyspnea", "ejection"], {"dyspnea": 2, "hypertension": 1}, {"dyspnea": 3200, "hypertension": 900}),
            (68, 102, 2, 3, ["spirometry"], {"spirometry": 1, "FEV1": 1}, {"spirometry": 4200, "FEV1": 2100}),
            (74, 94, 3, 3, ["exacerbation"], {"exacerbation": 1}, {"exacerbation": 2800}),
            (82, 84, 4, 3, [], {"COPD": 1}, {"COPD": 1400}),
        ]
        for comp, rt, su, lv, flags, wf, ht in demos:
            s = Session(
                patient_id=uwe.id,
                comprehension_score=comp,
                read_time_seconds=rt,
                self_understanding=su,
                difficulty_level=lv,
                flagged_word_count=len(flags),
                word_frequencies=json.dumps(wf),
                hover_times=json.dumps(ht),
            )
            db.add(s)
            db.flush()
            for w in flags:
                db.add(FlaggedWord(patient_id=uwe.id, session_id=s.id, word=w.lower()))
        db.commit()
    finally:
        db.close()


def init_db():
    """Create all tables on startup and seed demo data for test patient Uwe."""
    Base.metadata.create_all(bind=engine)
    _seed_uwe_demo()


def get_db():
    """Dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
