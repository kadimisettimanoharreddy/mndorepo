from pydantic import BaseModel, EmailStr, validator
from typing import Optional, Dict, Any
from datetime import datetime

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    department: str
    manager_email: EmailStr

    @validator('password')
    def validate_password(cls, v):
        """Validate password strength"""
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least 1 uppercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least 1 digit')
        # No 72-byte check needed with argon2
        return v

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class OTPVerify(BaseModel):
    email: EmailStr
    otp: str

class Token(BaseModel):
    access_token: str
    token_type: str

class InfrastructureRequestCreate(BaseModel):
    request_identifier: str
    cloud_provider: str
    environment: str
    resource_type: str
    parameters: Dict[str, Any]

class ChatMessage(BaseModel):
    message: str
    timestamp: Optional[datetime] = None