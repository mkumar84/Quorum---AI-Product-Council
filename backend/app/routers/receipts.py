import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(tags=["receipts"])


@router.post("/tasks/{task_id}/receipt", response_model=schemas.ReceiptOut, status_code=201)
def create_receipt(task_id: uuid.UUID, payload: schemas.ReceiptCreate, db: Session = Depends(get_db)):
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")

    receipt = models.Receipt(
        task_id=task_id,
        decided_at=datetime.datetime.now(datetime.timezone.utc),
        **payload.model_dump(),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


@router.get("/tasks/{task_id}/receipt", response_model=schemas.ReceiptOut)
def get_receipt(task_id: uuid.UUID, db: Session = Depends(get_db)):
    receipt = (
        db.query(models.Receipt)
        .filter(models.Receipt.task_id == task_id)
        .order_by(models.Receipt.decided_at.desc())
        .first()
    )
    if not receipt:
        raise HTTPException(status_code=404, detail="receipt not found")
    return receipt
