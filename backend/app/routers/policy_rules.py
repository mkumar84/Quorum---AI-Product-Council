from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/policy-rules", tags=["policy_rules"])


@router.post("", response_model=schemas.PolicyRuleOut, status_code=201)
def create_policy_rule(payload: schemas.PolicyRuleCreate, db: Session = Depends(get_db)):
    rule = models.PolicyRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("", response_model=list[schemas.PolicyRuleOut])
def list_policy_rules(db: Session = Depends(get_db)):
    return db.query(models.PolicyRule).all()
