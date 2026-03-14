from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.database import engine, Base
from app import models  # noqa: F401  # Import models to register metadata
from app.api.knowledge import router as knowledge_router
from app.api.quiz import router as quiz_router
from app.api.users import router as auth_router, user_router
from app.api.questions import router as questions_router
from app.api.admin import router as admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "ALTER TABLE IF EXISTS questions "
                "ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE IF EXISTS quiz_responses "
                "ADD COLUMN IF NOT EXISTS guessing_flag BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE IF EXISTS llm_runtime_config "
                "ADD COLUMN IF NOT EXISTS cat_enable_hybrid_llm_on_answer BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE IF EXISTS llm_runtime_config "
                "ADD COLUMN IF NOT EXISTS llm_api_key VARCHAR(500) NOT NULL DEFAULT ''"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE IF EXISTS llm_runtime_config "
                "ADD COLUMN IF NOT EXISTS llm_system_prompt TEXT NOT NULL DEFAULT ''"
            )
        )
    yield
    await engine.dispose()


app = FastAPI(
    title="KBS - Knowledge Based System",
    description="Hệ thống quản lý tri thức và kiểm tra năng lực dựa trên IRT",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(knowledge_router)
app.include_router(quiz_router)
app.include_router(questions_router)
app.include_router(admin_router)


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "service": "KBS API"}
