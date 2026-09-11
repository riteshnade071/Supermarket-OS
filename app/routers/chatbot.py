from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.core import User
from app.services.chatbot_service import ask_owner_assistant
from app.auth import get_current_user

router = APIRouter(prefix="/chatbot", tags=["Owner Assistant"])


class ChatbotQuestion(BaseModel):
    question: str
    store_id: str


@router.post("/ask")
async def ask(
    payload: ChatbotQuestion,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner asks anything — today's numbers or how to use a feature — and gets a Hinglish answer."""
    answer = await ask_owner_assistant(db, payload.store_id, payload.question)
    return {"answer": answer}
