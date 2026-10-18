@echo off
echo Starting Nixacom RFQ Backend and Frontend...

:: Start FastAPI Backend
start "Backend (FastAPI)" cmd /k "cd nixacom-rfq && venv\Scripts\activate && uvicorn app.main:app --reload --port 8000"

:: Start Next.js Frontend
start "Frontend (Next.js)" cmd /k "cd frontend && npm run dev"