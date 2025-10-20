from __future__ import annotations
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy import JSON
from datetime import datetime, timedelta
import uuid
from typing import Optional, Dict, Any
from .database import Base

class AllowedUser(Base):
    __tablename__ = "allowed_users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    department = Column(String(100), nullable=False)
    manager_email = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    department = Column(String(100), nullable=False)
    manager_email = Column(String(255), nullable=False)
    environment_access = Column(MutableDict.as_mutable(JSON), default=lambda: {"dev": False, "qa": False, "prod": False})
    environment_expiry = Column(MutableDict.as_mutable(JSON), default=dict)
    status = Column(String(20), default="active")
    otp_code = Column(String(6))
    otp_expires_at = Column(DateTime)
    reset_token = Column(String(255))
    reset_token_expires_at = Column(DateTime)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    requests = relationship("InfrastructureRequest", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("UserNotification", back_populates="user", cascade="all, delete-orphan")
    approvals = relationship("EnvironmentApproval", back_populates="user", cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.environment_access is None:
            self.environment_access = {"dev": False, "qa": False, "prod": False}
        self._set_department_based_access()

    def _set_department_based_access(self):
        department = (self.department or "").strip().lower()
        if department in ["devops", "engineering", "datascience"]:
            self.environment_access["dev"] = True

    def is_environment_active(self, environment: str) -> bool:
        access = (self.environment_access or {}).get(environment, False)
        if not access:
            return False
        expiry_dt = self.get_environment_expiry(environment)
        if expiry_dt and expiry_dt <= datetime.utcnow():
            return False
        return True

    def get_environment_expiry(self, environment: str) -> Optional[datetime]:
        expiry_map = self.environment_expiry or {}
        iso = expiry_map.get(environment)
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso)
        except Exception:
            return None

class EnvironmentApproval(Base):
    __tablename__ = "environment_approvals"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    environment = Column(String(20), nullable=False)
    approval_token = Column(String(255), unique=True, nullable=False)
    status = Column(String(20), default="pending")
    manager_email = Column(String(255), nullable=False)
    requested_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime)
    expires_at = Column(DateTime)
    user = relationship("User", back_populates="approvals")

class InfrastructureRequest(Base):
    __tablename__ = "infrastructure_requests"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    request_identifier = Column(String(100), unique=True, nullable=False)
    cloud_provider = Column(String(20), nullable=False)
    environment = Column(String(20), nullable=False)
    resource_type = Column(String(50), nullable=False)
    request_parameters = Column(JSON, nullable=False)
    status = Column(String(30), default="pending")
    pr_number = Column(Integer)
    hidden = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    deployed_at = Column(DateTime)
    user = relationship("User", back_populates="requests")
    terraform_state = relationship("TerraformState", back_populates="request", uselist=False, cascade="all, delete-orphan")
    notifications = relationship("UserNotification", back_populates="request", cascade="all, delete-orphan")

class TerraformState(Base):
    __tablename__ = "terraform_states"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("infrastructure_requests.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    request_identifier = Column(String(100), nullable=True)
    cloud_provider = Column(String(20), nullable=False)
    environment = Column(String(20), nullable=False)
    terraform_state_file_path = Column(String(500), nullable=True)  # Store file path instead of content
    terraform_outputs = Column(JSON, nullable=True)  # Store structured outputs
    resource_ids = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    destroyed_at = Column(DateTime)
    request = relationship("InfrastructureRequest", back_populates="terraform_state")
    user = relationship("User")

class UserNotification(Base):
    __tablename__ = "user_notifications"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    request_id = Column(UUID(as_uuid=True), ForeignKey("infrastructure_requests.id"), nullable=True)  # Made nullable
    notification_type = Column(String(50), nullable=False, default='deployment')
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(20), nullable=False)
    deployment_details = Column(JSON, nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)
    user = relationship("User", back_populates="notifications")
    request = relationship("InfrastructureRequest", back_populates="notifications")