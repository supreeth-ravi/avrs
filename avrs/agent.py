from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Mock BFSI database
# ---------------------------------------------------------------------------

_MOCK_DB: dict[str, Any] = {
    "customers": {
        "default": {
            "id": "CUST-10042",
            "name": "Supreeth",
            "phone": "+91-9876543210",
            "email": "supreeth.ravi@phronetic.ai",
            "policies": ["HS-2024-88821", "MV-2024-33201"],
            "accounts": ["SB-10042-001"],
        }
    },
    "policies": {
        "HS-2024-88821": {
            "type": "HealthShield Gold",
            "status": "active",
            "sum_insured": "50 lakhs",
            "premium": 5432,
            "frequency": "monthly",
            "next_due": "January 15, 2025",
            "expiry": "March 31, 2025",
            "network_hospitals": 8500,
            "customer": "Priya Sharma",
        },
        "MV-2024-33201": {
            "type": "Motor Comprehensive",
            "status": "active",
            "vehicle": "Honda City DL-01-AB-1234",
            "premium": 12800,
            "ncb": "25 percent",
            "expiry": "December 31, 2024",
            "customer": "Priya Sharma",
        },
    },
    "claims": {
        "CN-20241130-442": {
            "policy_id": "HS-2024-88821",
            "status": "Under Review",
            "amount": 28000,
            "filed_date": "November 30, 2024",
            "hospital": "Apollo Hospital",
            "reason": "Hospitalization for Dengue",
            "eta": "December 20, 2024",
        }
    },
    "accounts": {
        "SB-10042-001": {
            "type": "Savings",
            "balance": 142350,
            "last_txn": "December 1, 2024",
            "ifsc": "SAFE0001042",
        }
    },
}


# ---------------------------------------------------------------------------
# Agent personas — loaded from agents.yaml (project root)
# ---------------------------------------------------------------------------

def _load_agents() -> dict[str, dict]:
    yaml_path = Path(__file__).parent.parent / "agents.yaml"
    if yaml_path.exists():
        with yaml_path.open() as f:
            return yaml.safe_load(f)
    raise FileNotFoundError(f"agents.yaml not found at {yaml_path}")


AGENTS: dict[str, dict] = _load_agents()


# ---------------------------------------------------------------------------
# Tool implementations (mock lookups)
# ---------------------------------------------------------------------------

def _lookup_policy(policy_id: str | None = None, customer_name: str | None = None) -> dict:
    if policy_id and policy_id in _MOCK_DB["policies"]:
        return {"policy_id": policy_id, **_MOCK_DB["policies"][policy_id]}
    # Default to first policy
    cust = _MOCK_DB["customers"]["default"]
    pid = cust["policies"][0]
    return {"policy_id": pid, **_MOCK_DB["policies"][pid]}


def _get_claim_status(claim_id: str | None = None, policy_id: str | None = None) -> dict:
    if claim_id and claim_id in _MOCK_DB["claims"]:
        return {"claim_id": claim_id, **_MOCK_DB["claims"][claim_id]}
    # Default claim
    cid = "CN-20241130-442"
    return {"claim_id": cid, **_MOCK_DB["claims"][cid]}


def _get_account_balance(account_id: str | None = None) -> dict:
    acc_id = account_id or "SB-10042-001"
    acc = _MOCK_DB["accounts"].get(acc_id, _MOCK_DB["accounts"]["SB-10042-001"])
    return {"account_id": acc_id, **acc}


def _get_customer_policies(customer_name: str | None = None) -> dict:
    cust = _MOCK_DB["customers"]["default"]
    policies = [
        {"policy_id": pid, **_MOCK_DB["policies"][pid]}
        for pid in cust["policies"]
    ]
    return {"customer": cust["name"], "policies": policies}


_TOOLS = [
    {
        "name": "lookup_policy",
        "description": "Look up insurance policy details by policy ID or customer name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "policy_id": {"type": "string", "description": "Policy ID (e.g. HS-2024-88821)"},
                "customer_name": {"type": "string", "description": "Customer full name"},
            },
        },
    },
    {
        "name": "get_claim_status",
        "description": "Get the current status of an insurance claim.",
        "input_schema": {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string", "description": "Claim ID (e.g. CN-20241130-442)"},
                "policy_id": {"type": "string"},
            },
        },
    },
    {
        "name": "get_account_balance",
        "description": "Get bank account balance and recent transaction info.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
            },
        },
    },
    {
        "name": "get_customer_policies",
        "description": "List all policies for a customer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
            },
        },
    },
]

_TOOL_FNS = {
    "lookup_policy": _lookup_policy,
    "get_claim_status": _get_claim_status,
    "get_account_balance": _get_account_balance,
    "get_customer_policies": _get_customer_policies,
}


# ---------------------------------------------------------------------------
# Session and agent
# ---------------------------------------------------------------------------

@dataclass
class AgentSession:
    session_id: str
    agent_type: str
    history: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    turn_count: int = 0


class BFSIAgent:
    def __init__(self, agent_type: str = "insurance") -> None:
        if agent_type not in AGENTS:
            raise ValueError(f"Unknown agent: {agent_type!r}. Choose: {list(AGENTS)}")
        self.agent_type = agent_type
        self.persona = AGENTS[agent_type]

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY not set. Export it or put it in .env"
            )
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def respond(
        self,
        session: AgentSession,
        user_text: str,
    ) -> tuple[str, dict]:
        """
        Returns (avrs_text_template, slots_dict).
        avrs_text_template may contain {slot_key} markers.
        slots_dict maps slot_key -> value string.
        """
        session.history.append({"role": "user", "content": user_text})
        session.turn_count += 1

        raw_response = self._call_claude(session)

        session.history.append({"role": "assistant", "content": raw_response})

        text_template, slots = _parse_avrs_response(raw_response)
        return text_template, slots

    def _create_with_retry(self, model: str, system: str, messages: list, max_attempts: int = 4) -> object:
        import anthropic
        delay = 15.0
        for attempt in range(max_attempts):
            try:
                return self._client.messages.create(
                    model=model,
                    max_tokens=512,
                    system=system,
                    tools=_TOOLS,
                    messages=messages,
                )
            except anthropic.RateLimitError:
                if attempt == max_attempts - 1:
                    raise
                time.sleep(delay)
                delay *= 2

    def _build_system_prompt(self) -> str:
        cust = _MOCK_DB["customers"]["default"]
        context = (
            f"\nSESSION CONTEXT:\n"
            f"Authenticated customer: {cust['name']} (ID: {cust['id']}).\n"
            f"They are already verified — NEVER ask for their policy ID, claim ID, or name.\n"
            f"Call the lookup tools immediately (no args needed) to get their data, then "
            f"respond. Remember: always use a short semantic key like claim_id or eta inside "
            f"the curly braces — never the actual value itself."
        )
        return self.persona["system_prompt"] + context

    def _call_claude(self, session: AgentSession) -> str:
        messages = session.history[:]
        _model = os.getenv("AVRS_LLM_MODEL", "claude-haiku-4-5-20251001")
        system = self._build_system_prompt()

        response = self._create_with_retry(_model, system, messages)

        # Handle tool use agentic loop
        while response.stop_reason == "tool_use":
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            tool_results = []

            for tu in tool_uses:
                fn = _TOOL_FNS.get(tu.name)
                result = fn(**(tu.input or {})) if fn else {"error": "unknown tool"}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result),
                })

            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]

            response = self._create_with_retry(_model, system, messages)

        text_blocks = [b.text for b in response.content if hasattr(b, "text")]
        result = "\n".join(text_blocks).strip()
        if not result:
            return "I'm sorry, I wasn't able to process that. Could you please repeat your question?"
        return result


def _parse_avrs_response(raw: str) -> tuple[str, dict]:
    """Extract (text_template, slots) from agent response."""
    slots: dict = {}

    if "SLOTS:" in raw:
        parts = raw.split("SLOTS:", 1)
        text = parts[0].strip().strip('"')
        try:
            slots = json.loads(parts[1].strip())
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", parts[1], re.DOTALL)
            if m:
                try:
                    slots = json.loads(m.group())
                except Exception:
                    pass
        return text, slots

    return raw.strip().strip('"'), {}


# ---------------------------------------------------------------------------
# Session store (in-memory, swappable to Redis)
# ---------------------------------------------------------------------------

class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}

    def create(self, agent_type: str) -> AgentSession:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session = AgentSession(session_id=session_id, agent_type=agent_type)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())


_store = SessionStore()


def get_store() -> SessionStore:
    return _store
