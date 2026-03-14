from sqlalchemy import Column, Integer, String, Boolean, Float, Text
from app.database import Base


class LLMRuntimeConfig(Base):
    __tablename__ = "llm_runtime_config"

    id = Column(Integer, primary_key=True, default=1)
    llm_enabled = Column(Boolean, nullable=False, default=True)
    cat_enable_hybrid_llm_on_answer = Column(Boolean, nullable=False, default=False)
    llm_api_key = Column(String(500), nullable=False, default="")
    llm_system_prompt = Column(Text, nullable=False, default="")
    llm_base_url = Column(String(500), nullable=False, default="https://api.openai.com/v1")
    llm_model = Column(String(120), nullable=False, default="gpt-5.1")
    llm_temperature = Column(Float, nullable=False, default=0.2)
    llm_timeout_seconds = Column(Integer, nullable=False, default=30)
