from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables from the local .env file
load_dotenv()

from app.database import engine, Base
from app.models import RFQRecordModel
from app.routers import integrations, rfqs


# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Nixacom RFQ Automation", version="0.1.0")

# Enable CORS so the Next.js frontend can communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rfqs.router)
app.include_router(integrations.router)


@app.get("/health")
async def health():
    return {"status": "ok"}