"""Multi-tenant user management for Pickr — OTP, tiers, rate limits, virtual number pool.

Business flow:
  1. User enters phone number → OTP sent
  2. User verifies OTP → account created
  3. Backend auto-assigns virtual number from pool
  4. User sets call forwarding during onboarding
  5. Backend enforces pricing tier limits (minutes, calls/hour)
  6. Provider has full admin control via protected endpoints

Persistence: JSON files (users.json, otp_cache.json, number_pool.json).
Production: swap for PostgreSQL + Redis.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config / paths
# ---------------------------------------------------------------------------

_USERS_PATH = Path(os.getenv("AVRS_USERS_PATH", "users.json"))
_OTP_PATH = Path(os.getenv("AVRS_OTP_PATH", "otp_cache.json"))
_POOL_PATH = Path(os.getenv("AVRS_NUMBER_POOL_PATH", "number_pool.json"))

OTP_EXPIRY_SECONDS = int(os.getenv("AVRS_OTP_EXPIRY", "300"))     # 5 min
OTP_RESEND_SECONDS = int(os.getenv("AVRS_OTP_RESEND", "60"))      # 1 min

# ---------------------------------------------------------------------------
# Pricing tiers
# ---------------------------------------------------------------------------

TIERS: dict[str, dict] = {
    "free": {
        "monthly_minutes": 30,
        "max_calls_per_hour": 5,
        "max_contacts": 20,
        "features": ["basic_screening", "spam_detection"],
        "price_inr": 0,
    },
    "basic": {
        "monthly_minutes": 120,
        "max_calls_per_hour": 15,
        "max_contacts": 100,
        "features": ["basic_screening", "spam_detection", "custom_greeting", "call_transcript"],
        "price_inr": 199,
    },
    "pro": {
        "monthly_minutes": 500,
        "max_calls_per_hour": 30,
        "max_contacts": 500,
        "features": ["all"],
        "price_inr": 499,
    },
    "enterprise": {
        "monthly_minutes": -1,  # unlimited
        "max_calls_per_hour": 100,
        "max_contacts": -1,
        "features": ["all", "priority_support", "dedicated_number", "api_access"],
        "price_inr": 1999,
    },
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class User:
    user_id: str
    auth_token: str
    phone_number: str
    # Profile
    name: str = ""
    email: str | None = None
    avatar_url: str | None = None
    timezone: str = "Asia/Kolkata"
    language: str = "en-IN"
    # Assigned virtual number
    assigned_exotel_number: str | None = None
    # Controls
    enabled: bool = True
    screening_mode: str = "ai"  # ai | silent | block_all | allow_all
    greeting: str = "Hello, this is Pickr. Who may I say is calling?"
    persona: str = "screener"
    voice_id: str | None = None
    # Pricing / usage
    pricing_tier: str = "free"
    monthly_minutes_limit: int = 30
    monthly_minutes_used: float = 0.0
    billing_cycle_start: float = 0.0
    # Rate limit tracking: list of call start timestamps (last hour)
    calls_this_hour: list[float] = field(default_factory=list)
    # Contact rules
    contact_rules: dict[str, dict] = field(default_factory=dict)
    # Call history
    call_history: list[dict] = field(default_factory=list)
    # Onboarding
    onboarding_complete: bool = False
    onboarding_step: str = "phone_verify"  # phone_verify | number_assigned | forwarding_done | complete
    # Metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "User":
        return cls(
            user_id=d["user_id"],
            auth_token=d["auth_token"],
            phone_number=d["phone_number"],
            name=d.get("name", ""),
            email=d.get("email"),
            avatar_url=d.get("avatar_url"),
            timezone=d.get("timezone", "Asia/Kolkata"),
            language=d.get("language", "en-IN"),
            assigned_exotel_number=d.get("assigned_exotel_number"),
            enabled=d.get("enabled", True),
            screening_mode=d.get("screening_mode", "ai"),
            greeting=d.get("greeting", "Hello, this is Pickr. Who may I say is calling?"),
            persona=d.get("persona", "screener"),
            voice_id=d.get("voice_id"),
            pricing_tier=d.get("pricing_tier", "free"),
            monthly_minutes_limit=d.get("monthly_minutes_limit", 30),
            monthly_minutes_used=d.get("monthly_minutes_used", 0.0),
            billing_cycle_start=d.get("billing_cycle_start", 0.0),
            calls_this_hour=d.get("calls_this_hour", []),
            contact_rules=d.get("contact_rules", {}),
            call_history=d.get("call_history", []),
            onboarding_complete=d.get("onboarding_complete", False),
            onboarding_step=d.get("onboarding_step", "phone_verify"),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            settings=d.get("settings", {}),
        )

    def refresh_billing_cycle(self) -> None:
        """Reset monthly usage if a new month has started."""
        now = time.time()
        if self.billing_cycle_start == 0:
            self.billing_cycle_start = now
            return
        # Simple month boundary check (30-day cycles for MVP)
        if now - self.billing_cycle_start >= 30 * 86400:
            self.monthly_minutes_used = 0.0
            self.billing_cycle_start = now

    def can_accept_call(self) -> tuple[bool, str]:
        """Check rate limits and tier before accepting a new call."""
        if not self.enabled:
            return False, "account_disabled"

        self.refresh_billing_cycle()

        tier = TIERS.get(self.pricing_tier, TIERS["free"])
        limit = tier["monthly_minutes"]
        if limit >= 0 and self.monthly_minutes_used >= limit:
            return False, "monthly_minute_limit_reached"

        # Clean old call timestamps (> 1 hour)
        cutoff = time.time() - 3600
        self.calls_this_hour = [t for t in self.calls_this_hour if t > cutoff]
        if len(self.calls_this_hour) >= tier["max_calls_per_hour"]:
            return False, "hourly_call_limit_reached"

        return True, "ok"

    def record_call_start(self) -> None:
        self.calls_this_hour.append(time.time())

    def record_call_minutes(self, minutes: float) -> None:
        self.monthly_minutes_used += minutes
        self.updated_at = time.time()


# ---------------------------------------------------------------------------
# OTP cache
# ---------------------------------------------------------------------------

_otp_cache: dict[str, dict] = {}  # phone_norm -> {"otp": str, "expires": float, "attempts": int}


def _persist_otp() -> None:
    try:
        _OTP_PATH.write_text(json.dumps(_otp_cache, default=str), encoding="utf-8")
    except Exception as e:
        log.warning("Failed to persist OTP cache: %s", e)


def _load_otp() -> None:
    global _otp_cache
    if not _OTP_PATH.exists():
        return
    try:
        _otp_cache = json.loads(_OTP_PATH.read_text(encoding="utf-8"))
        # Clean expired entries
        now = time.time()
        _otp_cache = {
            k: v for k, v in _otp_cache.items()
            if v.get("expires", 0) > now
        }
    except Exception as e:
        log.warning("Failed to load OTP cache: %s", e)


_load_otp()


def generate_otp(phone_number: str) -> tuple[str, float]:
    """Generate a 6-digit OTP for the given phone. Returns (otp, expires_at)."""
    phone = _norm_phone(phone_number)
    now = time.time()

    existing = _otp_cache.get(phone)
    if existing and now - existing.get("created_at", 0) < OTP_RESEND_SECONDS:
        raise ValueError(f"Please wait {OTP_RESEND_SECONDS}s before requesting a new OTP")

    otp = f"{secrets.randbelow(1_000_000):06d}"
    expires = now + OTP_EXPIRY_SECONDS
    _otp_cache[phone] = {
        "otp": otp,
        "expires": expires,
        "created_at": now,
        "attempts": 0,
    }
    _persist_otp()
    log.info("OTP generated for %s (expires in %ds)", phone, OTP_EXPIRY_SECONDS)
    return otp, expires


def verify_otp(phone_number: str, otp: str) -> bool:
    """Verify OTP. Returns True if valid. Auto-clears on success or too many failures."""
    phone = _norm_phone(phone_number)
    entry = _otp_cache.get(phone)
    if not entry:
        return False

    if time.time() > entry["expires"]:
        _otp_cache.pop(phone, None)
        _persist_otp()
        return False

    entry["attempts"] = entry.get("attempts", 0) + 1
    if entry["attempts"] > 5:
        _otp_cache.pop(phone, None)
        _persist_otp()
        return False

    if entry["otp"] == otp.strip():
        _otp_cache.pop(phone, None)
        _persist_otp()
        return True

    _persist_otp()
    return False


# ---------------------------------------------------------------------------
# Virtual number pool
# ---------------------------------------------------------------------------

_number_pool: dict[str, dict] = {}  # number -> {"status": str, "assigned_to": str|None, "region": str}


def _persist_pool() -> None:
    try:
        _POOL_PATH.write_text(json.dumps(_number_pool, default=str), encoding="utf-8")
    except Exception as e:
        log.warning("Failed to persist number pool: %s", e)


def _load_pool() -> None:
    global _number_pool
    if not _POOL_PATH.exists():
        return
    try:
        _number_pool = json.loads(_POOL_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Failed to load number pool: %s", e)


_load_pool()


def add_number_to_pool(number: str, region: str = "IN") -> None:
    """Admin adds a virtual number to the available pool."""
    num = _norm_phone(number)
    _number_pool[num] = {
        "status": "available",
        "assigned_to": None,
        "region": region,
        "provider": "exotel",
    }
    _persist_pool()


def remove_number_from_pool(number: str) -> None:
    """Admin removes a number from the pool."""
    num = _norm_phone(number)
    _number_pool.pop(num, None)
    _persist_pool()


def list_available_numbers() -> list[str]:
    return [
        n for n, meta in _number_pool.items()
        if meta.get("status") == "available"
    ]


def list_pool() -> dict[str, dict]:
    return dict(_number_pool)


def auto_assign_number(user_id: str, region: str = "IN") -> str:
    """Pick the first available number and assign it to the user."""
    available = [
        n for n, meta in _number_pool.items()
        if meta.get("status") == "available" and meta.get("region", "IN") == region
    ]
    if not available:
        raise ValueError("No virtual numbers available in pool")

    chosen = available[0]
    _number_pool[chosen]["status"] = "assigned"
    _number_pool[chosen]["assigned_to"] = user_id
    _persist_pool()

    # Also update user record
    user = _users_by_id.get(user_id)
    if user:
        user.assigned_exotel_number = chosen
        user.onboarding_step = "number_assigned"
        _users_by_exotel[_norm_phone(chosen)] = user
        _persist()

    log.info("Auto-assigned %s to user %s", chosen, user_id)
    return chosen


def release_number(number: str) -> None:
    """Release a number back to the pool (e.g. on user deletion)."""
    num = _norm_phone(number)
    if num in _number_pool:
        _number_pool[num]["status"] = "available"
        _number_pool[num]["assigned_to"] = None
        _persist_pool()


# ---------------------------------------------------------------------------
# In-memory user cache
# ---------------------------------------------------------------------------

_users_by_id: dict[str, User] = {}
_users_by_token: dict[str, User] = {}
_users_by_exotel: dict[str, User] = {}
_users_by_phone: dict[str, User] = {}


def _persist() -> None:
    try:
        data = {uid: u.to_dict() for uid, u in _users_by_id.items()}
        _USERS_PATH.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        log.warning("Failed to persist users: %s", e)


def _load() -> None:
    global _users_by_id, _users_by_token, _users_by_exotel, _users_by_phone
    if not _USERS_PATH.exists():
        return
    try:
        data = json.loads(_USERS_PATH.read_text(encoding="utf-8"))
        _users_by_id = {}
        _users_by_token = {}
        _users_by_exotel = {}
        _users_by_phone = {}
        for uid, udict in data.items():
            user = User.from_dict(udict)
            _users_by_id[user.user_id] = user
            _users_by_token[user.auth_token] = user
            _users_by_phone[_norm_phone(user.phone_number)] = user
            if user.assigned_exotel_number:
                _users_by_exotel[_norm_phone(user.assigned_exotel_number)] = user
        log.info("Loaded %d users from %s", len(_users_by_id), _USERS_PATH)
    except Exception as e:
        log.warning("Failed to load users: %s", e)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_user(phone_number: str, name: str = "") -> User:
    """Register a new subscriber after OTP verification."""
    phone = _norm_phone(phone_number)
    if phone in _users_by_phone:
        raise ValueError(f"User with phone {phone} already exists")

    tier = TIERS["free"]
    user = User(
        user_id=f"usr_{uuid.uuid4().hex[:12]}",
        auth_token=f"tk_{secrets.token_urlsafe(24)}",
        phone_number=phone,
        name=name or phone,
        pricing_tier="free",
        monthly_minutes_limit=tier["monthly_minutes"],
        billing_cycle_start=time.time(),
    )
    _users_by_id[user.user_id] = user
    _users_by_token[user.auth_token] = user
    _users_by_phone[phone] = user
    _persist()
    log.info("Created user %s phone=%s", user.user_id, phone)
    return user


def get_user_by_token(token: str) -> User | None:
    return _users_by_token.get(token)


def get_user_by_id(user_id: str) -> User | None:
    return _users_by_id.get(user_id)


def get_user_by_phone(phone: str) -> User | None:
    return _users_by_phone.get(_norm_phone(phone))


def get_user_by_exotel(exotel_number: str) -> User | None:
    return _users_by_exotel.get(_norm_phone(exotel_number))


def update_user(user_id: str, **fields) -> User:
    user = _users_by_id.get(user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")

    old_exotel = user.assigned_exotel_number
    for k, v in fields.items():
        if hasattr(user, k):
            setattr(user, k, v)
    user.updated_at = time.time()

    # Re-index if exotel changed
    if old_exotel != user.assigned_exotel_number:
        if old_exotel:
            _users_by_exotel.pop(_norm_phone(old_exotel), None)
        if user.assigned_exotel_number:
            _users_by_exotel[_norm_phone(user.assigned_exotel_number)] = user

    _persist()
    return user


def delete_user(user_id: str) -> bool:
    user = _users_by_id.pop(user_id, None)
    if not user:
        return False
    _users_by_token.pop(user.auth_token, None)
    _users_by_phone.pop(_norm_phone(user.phone_number), None)
    if user.assigned_exotel_number:
        _users_by_exotel.pop(_norm_phone(user.assigned_exotel_number), None)
        release_number(user.assigned_exotel_number)
    _persist()
    log.info("Deleted user %s", user_id)
    return True


def set_user_tier(user_id: str, tier_name: str) -> User:
    if tier_name not in TIERS:
        raise ValueError(f"Unknown tier: {tier_name}")
    tier = TIERS[tier_name]
    return update_user(
        user_id,
        pricing_tier=tier_name,
        monthly_minutes_limit=tier["monthly_minutes"],
    )


# ── Contact rules ───────────────────────────────────────────────────────────

def add_contact_rule(user_id: str, phone: str, rule_type: str, name: str = "") -> None:
    user = _users_by_id.get(user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")
    user.contact_rules[_norm_phone(phone)] = {"type": rule_type, "name": name}
    _persist()


def remove_contact_rule(user_id: str, phone: str) -> None:
    user = _users_by_id.get(user_id)
    if not user:
        return
    user.contact_rules.pop(_norm_phone(phone), None)
    _persist()


def is_whitelisted(user_id: str, phone: str) -> bool:
    user = _users_by_id.get(user_id)
    if not user:
        return False
    return user.contact_rules.get(_norm_phone(phone), {}).get("type") == "whitelist"


def is_blocked(user_id: str, phone: str) -> bool:
    user = _users_by_id.get(user_id)
    if not user:
        return False
    return user.contact_rules.get(_norm_phone(phone), {}).get("type") == "blocklist"


# ── Call history ────────────────────────────────────────────────────────────

def add_call_history(user_id: str, record: dict) -> None:
    user = _users_by_id.get(user_id)
    if not user:
        return
    record["timestamp"] = time.time()
    user.call_history.insert(0, record)
    if len(user.call_history) > 500:
        user.call_history = user.call_history[:500]
    _persist()


def list_users() -> list[User]:
    return list(_users_by_id.values())


# ── Helpers ──────────────────────────────────────────────────────────────────

def _norm_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if phone.strip().startswith("+"):
        return "+" + digits
    return digits


# Load persisted data after all helpers are defined
_load()
