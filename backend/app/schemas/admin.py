from pydantic import BaseModel, Field


class LLMRuntimeConfigOut(BaseModel):
    llm_enabled: bool
    cat_enable_hybrid_llm_on_answer: bool
    has_llm_api_key: bool
    llm_system_prompt: str
    llm_base_url: str
    llm_model: str
    llm_temperature: float
    llm_timeout_seconds: int


class LLMRuntimeConfigUpdate(BaseModel):
    llm_enabled: bool
    cat_enable_hybrid_llm_on_answer: bool
    llm_api_key: str | None = Field(default=None, max_length=500)
    llm_system_prompt: str = Field(min_length=1)
    llm_base_url: str = Field(min_length=1, max_length=500)
    llm_model: str = Field(min_length=1, max_length=120)
    llm_temperature: float = Field(ge=0.0, le=2.0)
    llm_timeout_seconds: int = Field(ge=1, le=300)
