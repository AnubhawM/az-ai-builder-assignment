from sqlalchemy.orm import Session
from database.models import User

# User CRUD Operations (existing)
def create_user(db: Session, user_data: dict):
    new_user = User(
        auth0_id=user_data['auth0_id'],
        email=user_data['email'],
        name=user_data['name'],
        role=user_data.get('role', 'user'),
        status=user_data.get('status', 'active')
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()

def get_user_by_auth0_id(db: Session, auth0_id: str):
    return db.query(User).filter(User.auth0_id == auth0_id).first()

def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(User).offset(skip).limit(limit).all()

def update_user(db: Session, user_id: int, user_data: dict):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        for key, value in user_data.items():
            setattr(user, key, value)
        db.commit()
        db.refresh(user)
    return user

def delete_user(db: Session, user_id: int):
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
    return user
