from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import os
import re
from datetime import datetime, timedelta

from bson import ObjectId

from app.database import get_users_collection
from app.models.user import UserCreate, UserResponse, LoginRequest, Token
from app.core.security import (
    verify_password, 
    get_password_hash, 
    create_access_token, 
    decode_token
)
from app.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])
# Swagger OAuth2 uses form fields username+password; /auth/login expects JSON — use /auth/token for UI "Authorize".
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def user_doc_to_response(user: dict) -> UserResponse:
    """Strip Mongo fields and satisfy UserResponse (username required)."""
    u = {**user}
    u["id"] = str(u.pop("_id"))
    u.pop("hashed_password", None)
    # Normalize naming fields between DB and frontend.
    if not u.get("full_name") and u.get("name"):
        u["full_name"] = u.get("name")
    if not u.get("username"):
        email = u.get("email") or ""
        u["username"] = email.split("@")[0] or "user"
    if "availability" not in u or u.get("availability") is None:
        u["availability"] = True
    # Normalize skills to [{ skill_name, proficiency_level: float }]
    raw_skills = u.get("skills") or []
    norm: list[dict] = []
    for s in raw_skills:
        if isinstance(s, dict) and s.get("skill_name"):
            norm.append(
                {
                    "skill_name": str(s["skill_name"]).strip(),
                    "proficiency_level": float(s.get("proficiency_level") or 1.0),
                }
            )
        elif isinstance(s, str) and s.strip():
            norm.append({"skill_name": s.strip(), "proficiency_level": 1.0})
    u["skills"] = norm
    return UserResponse(**u)


def _looks_like_object_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{24}", str(value or "").strip()))


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Your session could not be verified. Please sign in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token_data = decode_token(token)
    if token_data is None:
        raise credentials_exception
    
    users_collection = get_users_collection()
    email_raw = str(token_data.email or "").strip()
    user = await users_collection.find_one({"email": email_raw}) if email_raw else None

    if user is None and email_raw:
        em_lower = email_raw.lower()
        user = await users_collection.find_one({"email": em_lower})
    if user is None and email_raw:
        user = await users_collection.find_one(
            {"email": {"$regex": f"^{re.escape(email_raw.lower())}$", "$options": "i"}}
        )
    if user is None and token_data.user_id and _looks_like_object_id(str(token_data.user_id)):
        try:
            user = await users_collection.find_one({"_id": ObjectId(str(token_data.user_id).strip())})
        except Exception:
            user = None

    if user is None:
        raise credentials_exception

    return user_doc_to_response(user)

@router.post("/register", response_model=Token)
async def register(user_data: UserCreate):
    users_collection = get_users_collection()
    
    # Check if user already exists
    existing_user = await users_collection.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That email is already registered. Try logging in or use a different email.",
        )
    
    # Hash password
    hashed_password = get_password_hash(user_data.password)
    
    # Create user document
    user_dict = user_data.model_dump(exclude={"password"})
    user_dict["hashed_password"] = hashed_password
    user_dict["created_at"] = datetime.utcnow()
    user_dict["updated_at"] = datetime.utcnow()
    
    if "role" not in user_dict or not user_dict["role"]:
        user_dict["role"] = "developer"
    if user_dict.get("role") == "admin" and os.getenv("ALLOW_PUBLIC_ADMIN_REG", "").lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The CEO admin account is provisioned by the system. Sign up as Developer or Manager.",
        )
    
    # Insert user
    result = await users_collection.insert_one(user_dict)
    
    # Get created user
    created_user = await users_collection.find_one({"_id": result.inserted_id})
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": created_user["email"],
            "user_id": str(created_user["_id"]),
            "role": created_user.get("role", "developer")
        },
        expires_delta=access_token_expires
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=user_doc_to_response(created_user),
    )

async def _issue_token_for_email_password(email: str, password: str) -> Token:
    users_collection = get_users_collection()
    normalized_email = str(email).strip().lower()
    print(f"[AUTH] Login attempt for email: {normalized_email}")

    user = await users_collection.find_one({"email": normalized_email})
    if user is None:
        # Fallback for legacy mixed-case emails in old seed data.
        user = await users_collection.find_one(
            {"email": {"$regex": f"^{re.escape(normalized_email)}$", "$options": "i"}}
        )

    password_match = bool(user and verify_password(password, user.get("hashed_password", "")))
    print(f"[AUTH] User found: {user is not None}, Password match: {password_match}")

    if not user or not password_match:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="We could not sign you in. Check your email and password, then try again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user["email"],
            "user_id": str(user["_id"]),
            "role": user.get("role", "developer"),
        },
        expires_delta=access_token_expires,
    )
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=user_doc_to_response(user),
    )


@router.post("/token", response_model=Token)
async def login_oauth2_form(form_data: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 password flow (form body). Swagger passes `username` — use your email there."""
    return await _issue_token_for_email_password(form_data.username, form_data.password)


@router.post("/login", response_model=Token)
async def login(login_data: LoginRequest):
    return await _issue_token_for_email_password(login_data.email, login_data.password)

@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: UserResponse = Depends(get_current_user)):
    return current_user


@router.post("/logout")
async def logout():
    """JWT is stateless — discard the token on the client."""
    return {"detail": "Signed out. Remove token from client storage."}