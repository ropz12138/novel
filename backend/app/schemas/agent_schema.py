from pydantic import BaseModel, Field


# --- Request schemas ---

class AgentStartRequest(BaseModel):
    """Start a new agent session for a chapter."""
    instruction: str = Field(default="", max_length=2000)


class AgentResumeRequest(BaseModel):
    """Resume a paused agent with user feedback."""
    action: str = Field(description="confirm / reject / guide")
    instruction: str = Field(default="", max_length=2000)


# --- SSE event schemas (for documentation/type safety) ---

class SSEEvent:
    """Helper to format SSE events."""
    @staticmethod
    def format(event: str, data: dict) -> str:
        import json
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
