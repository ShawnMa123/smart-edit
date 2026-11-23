"""Strict request DTOs for auth/organization/activity/developer endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(Strict):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=512)
    display_name: str | None = Field(default=None, max_length=120)
    organization_name: str | None = Field(default=None, max_length=200)


class LoginRequest(Strict):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=512)


class SwitchOrgRequest(Strict):
    org_id: str = Field(min_length=1, max_length=128)


class OrganizationCreate(Strict):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=80)


class OrganizationUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=80)


class DepartmentCreate(Strict):
    name: str = Field(min_length=1, max_length=200)
    parent_id: str | None = Field(default=None, max_length=128)


class DepartmentUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: str | None = Field(default=None, max_length=128)


class InviteCreate(Strict):
    email: str = Field(min_length=3, max_length=254)
    role_key: str = Field(min_length=1, max_length=64)
    department_id: str | None = Field(default=None, max_length=128)


class InviteAccept(Strict):
    invite_token: str = Field(min_length=8, max_length=256)


class RoleAssignmentCreate(Strict):
    user_id: str = Field(min_length=1, max_length=128)
    role_key: str = Field(min_length=1, max_length=64)
    scope_type: Literal["org", "department"] = "org"
    scope_id: str | None = Field(default=None, max_length=128)


class MemberStatusUpdate(Strict):
    status: Literal["active", "suspended", "removed"]


class ApiKeyCreate(Strict):
    name: str = Field(min_length=1, max_length=120)
    department_id: str | None = Field(default=None, max_length=128)
    scopes: list[str] | None = None
    expires_at: str | None = Field(default=None, max_length=64)


__all__ = [
    "ApiKeyCreate",
    "DepartmentCreate",
    "DepartmentUpdate",
    "InviteAccept",
    "InviteCreate",
    "LoginRequest",
    "MemberStatusUpdate",
    "OrganizationCreate",
    "RegisterRequest",
    "RoleAssignmentCreate",
    "Strict",
    "SwitchOrgRequest",
]