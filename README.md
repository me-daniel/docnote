# MedBridge — FastAPI Backend

## Setup

### 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your Anthropic API key
```bash
# Mac/Linux
export ANTHROPIC_API_KEY=sk-ant-...

# Windows (Command Prompt)
set ANTHROPIC_API_KEY=sk-ant-...

# Windows (PowerShell)
$env:ANTHROPIC_API_KEY="sk-ant-..."
```

### 3. Run the server
```bash
uvicorn main:app --reload --port 8000
```

### 4. Open in browser
```
http://localhost:8000
```

### 5. View auto-generated API docs
```
http://localhost:8000/docs        # Swagger UI
http://localhost:8000/redoc       # ReDoc
```

---

## Project Structure

```
medbridge_fastapi/
├── main.py          # FastAPI app — all routes
├── models.py        # SQLAlchemy ORM models (Patient, Session, FlaggedWord)
├── database.py      # DB engine, session, init_db()
├── requirements.txt
├── medbridge.db     # SQLite database (auto-created on first run)
├── templates/
│   └── index.html   # Frontend HTML (copy your medbridge.html here)
└── static/
    └── app.js       # Frontend JS — calls FastAPI instead of Anthropic directly
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/patients` | List all patients |
| POST | `/api/patients` | Create patient |
| GET | `/api/patients/{id}` | Get patient profile |
| GET | `/api/patients/{id}/sessions` | Get all sessions |
| POST | `/api/sessions` | Save a reading session |
| GET | `/api/patients/{id}/analytics` | Full analytics data |
| GET | `/api/patients/{id}/challenging-words` | Ranked difficult words |
| POST | `/api/simplify` | Simplify clinical text with Claude |
| POST | `/api/check-similarity` | Sentence-level similarity check |
| POST | `/api/define` | Get plain-English word definition |
| POST | `/api/patient-insight` | AI patient reading profile |
| POST | `/api/analytics-summary` | AI writing recommendations |

---

## How to integrate the frontend

1. Copy your `medbridge.html` into `templates/index.html`
2. Add `<script src="/static/app.js"></script>` before `</body>`
3. Remove the inline `<script>` block from the HTML (all logic is now in `app.js`)
4. The frontend now calls `/api/*` instead of `api.anthropic.com` directly

---

## Why FastAPI over Flask?

- **Async by default** — handles multiple concurrent AI calls without blocking
- **Auto docs** — Swagger UI at `/docs` for free
- **Pydantic validation** — request/response types validated automatically
- **Much faster** — built on Starlette + uvicorn (ASGI vs Flask's WSGI)
- **Type hints** — cleaner, more maintainable Python code
