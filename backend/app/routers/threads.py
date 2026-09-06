import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/threads", tags=["threads"])


@router.get("/{thread_id}", response_model=schemas.ThreadOut)
def get_thread(thread_id: uuid.UUID, db: Session = Depends(get_db)):
    thread = db.get(models.Thread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="thread not found")
    return thread


@router.get("/{thread_id}/messages", response_model=list[schemas.MessageOut])
def list_messages(thread_id: uuid.UUID, db: Session = Depends(get_db)):
    thread = db.get(models.Thread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="thread not found")
    return (
        db.query(models.Message)
        .filter(models.Message.thread_id == thread_id)
        .order_by(models.Message.created_at)
        .all()
    )


@router.post("/{thread_id}/messages", response_model=schemas.MessageOut, status_code=201)
def post_message(thread_id: uuid.UUID, payload: schemas.MessageCreate, db: Session = Depends(get_db)):
    thread = db.get(models.Thread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="thread not found")
    message = models.Message(thread_id=thread_id, **payload.model_dump())
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
