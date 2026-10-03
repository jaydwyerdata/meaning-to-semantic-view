"""Shared checks, inlined into each stored procedure by tools/build_sql.py."""
import json
import re

IDENT = re.compile(r"^[A-Z][A-Z0-9_]{0,254}$")
MAPPER_ROLE = "SVC_MAPPER"


def check_ident(name: str) -> str:
    """Reject anything that is not a plain unquoted identifier before it reaches dynamic SQL."""
    if not IDENT.match(name or ""):
        raise ValueError(f"Not a plain identifier: {name!r}")
    return name


def secondary_roles_off(raw: str) -> bool:
    """CURRENT_SECONDARY_ROLES() returns JSON; isolation needs its roles list to be empty."""
    try:
        roles = json.loads(raw).get("roles", "")
    except (TypeError, ValueError):
        return False
    return roles in ("", None, [])


def require_mapper_role(session) -> None:
    """Refuse to run unless the session is SVC_MAPPER alone. Secondary roles would let the
    procedure inherit the user's other roles and read the answer key, defeating ADR-012."""
    role, secondary = session.sql("SELECT CURRENT_ROLE(), CURRENT_SECONDARY_ROLES()").collect()[0]
    if role != MAPPER_ROLE or not secondary_roles_off(secondary):
        raise PermissionError(
            f"Run as {MAPPER_ROLE} with secondary roles off: "
            f"USE ROLE {MAPPER_ROLE}; USE SECONDARY ROLES NONE;  (current: {role}, {secondary})"
        )
