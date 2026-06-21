from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from pydantic import BaseModel, EmailStr, Field


class PyObjectId(ObjectId):
    pass


class Skill(BaseModel):
    skill_name: str
    # SDS: dynamic updates may use half-steps (e.g. +0.5); stored as number for JSON/Mongo.
    proficiency_level: float = Field(ge=1.0, le=5.0)


class UserBase(BaseModel):
    # Use robust email parsing instead of fragile regex checks.
    email: EmailStr

    # Frontend sends `name`; older DB may store `username`.
    username: Optional[str] = None
    name: Optional[str] = None
    full_name: Optional[str] = None
    gender: Optional[str] = Field(
        default=None,
        description="Optional gender hint for natural-language responses (e.g., male/female).",
    )

    # SDS-style: skills as objects with proficiency.
    skills: List[Skill] = Field(default_factory=list)

    role: str = Field(
        default="developer",
        description="One of: admin, manager (PM), developer",
    )

    availability: bool = True
    experience_years: float = 0.0
    cgpa: float = 0.0
    performance_history: List[float] = Field(default_factory=list)
    current_workload: int = 0

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    username: Optional[str] = None
    name: Optional[str] = None
    full_name: Optional[str] = None
    gender: Optional[str] = None
    skills: Optional[List[Skill]] = None
    role: Optional[str] = None
    availability: Optional[bool] = None
    experience_years: Optional[float] = None
    cgpa: Optional[float] = None
    performance_history: Optional[List[float]] = None
    current_workload: Optional[int] = None

class UserResponse(UserBase):
    # str (not EmailStr) — seed/demo rows like manager@demo.local must round-trip without 500 on login.
    email: str
    id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse  # Add this line

class TokenData(BaseModel):
    email: Optional[str] = None
    user_id: Optional[str] = None
    role: Optional[str] = None

class UserInDB(UserBase):
    id: str
    hashed_password: str
    disabled: bool = False