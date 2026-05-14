"""Radar MCP endpoint — Cordyceps agent tool bridge.

Exposes Radar data to Cordyceps agents via a simple JSON API.
Authentication: X-Radar-Key header (set RADAR_MCP_KEY in .env).

Endpoints
---------
GET  /mcp/schema   — list available tools + JSON schemas
POST /mcp/call     — execute a tool, return JSON result

Tools
-----
- list_customers    : paginated customer list with basic info
- get_customer      : customer detail + latest credit score by id or account_code
- risk_summary      : portfolio-level risk statistics
- score_history     : credit score history for a customer (last N records)
"""

from __future__ import annotations

import json
import os
from functools import wraps

from flask import Blueprint, jsonify, request

from database import AgingRecord, CreditRequest, CreditScore, Customer, get_session

mcp_bp = Blueprint("mcp", __name__, url_prefix="/mcp")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_MCP_KEY = os.environ.get("RADAR_MCP_KEY", "")


def _require_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _MCP_KEY:
            return jsonify({"error": "RADAR_MCP_KEY not configured on server"}), 503
        given = (
            request.headers.get("X-Radar-Key")
            or request.args.get("key")
            or ""
        )
        if given != _MCP_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "list_customers",
        "description": (
            "List customers in the Radar database with basic info "
            "(id, account_name, account_code, sector, credit_note). "
            "Use this to find a customer ID before calling get_customer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Optional name or account_code filter (case-insensitive contains)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 20, max 100)"
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_customer",
        "description": (
            "Get full customer profile including latest credit score, "
            "IFRS9 metrics, Z-score, and decision summary."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "Customer primary key (use list_customers to find it)"
                },
                "account_code": {
                    "type": "string",
                    "description": "Unique account code (alternative to customer_id)"
                },
            },
            "required": [],
        },
    },
    {
        "name": "risk_summary",
        "description": (
            "Portfolio-level risk statistics: customer count, "
            "credit note distribution, average scores, IFRS9 stage breakdown, "
            "total recommended limits."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sector": {
                    "type": "string",
                    "description": "Optional sector filter (e.g. 'retail', 'manufacturing')"
                },
            },
            "required": [],
        },
    },
    {
        "name": "score_history",
        "description": "Credit score history for a customer (most recent first).",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "integer", "description": "Customer ID"},
                "limit": {
                    "type": "integer",
                    "description": "Number of historical records to return (default 5)"
                },
            },
            "required": ["customer_id"],
        },
    },
]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@mcp_bp.get("/schema")
@_require_key
def schema():
    return jsonify({"tools": TOOLS})


@mcp_bp.post("/call")
@_require_key
def call():
    body = request.get_json(silent=True) or {}
    tool = body.get("tool", "")
    args = body.get("arguments", {})

    dispatch = {
        "list_customers": _list_customers,
        "get_customer": _get_customer,
        "risk_summary": _risk_summary,
        "score_history": _score_history,
    }
    fn = dispatch.get(tool)
    if fn is None:
        return jsonify({"error": f"Unknown tool: {tool!r}"}), 400

    try:
        result = fn(**args)
        return jsonify({"ok": True, "result": result})
    except TypeError as exc:
        return jsonify({"ok": False, "error": f"Bad arguments: {exc}"}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": repr(exc)}), 500


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _list_customers(search: str = "", limit: int = 20) -> list[dict]:
    limit = min(int(limit), 100)
    session = get_session()
    try:
        q = session.query(Customer)
        if search:
            like = f"%{search}%"
            q = q.filter(
                Customer.account_name.ilike(like)
                | Customer.account_code.ilike(like)
            )
        customers = q.order_by(Customer.account_name).limit(limit).all()
        return [
            {
                "id": c.id,
                "account_name": c.account_name,
                "account_code": c.account_code,
                "sector": c.sector,
                "tax_no": c.tax_no,
                "credit_note": _latest_note(session, c.id),
            }
            for c in customers
        ]
    finally:
        session.close()


def _get_customer(customer_id: int | None = None, account_code: str | None = None) -> dict:
    if customer_id is None and account_code is None:
        raise TypeError("Provide customer_id or account_code")
    session = get_session()
    try:
        q = session.query(Customer)
        if customer_id is not None:
            c = q.filter_by(id=int(customer_id)).first()
        else:
            c = q.filter_by(account_code=account_code).first()
        if c is None:
            return {"error": "Customer not found"}

        score = (
            session.query(CreditScore)
            .filter_by(customer_id=c.id)
            .order_by(CreditScore.calculated_at.desc())
            .first()
        )
        latest_request = (
            session.query(CreditRequest)
            .filter_by(customer_id=c.id)
            .order_by(CreditRequest.request_date.desc())
            .first()
        )

        result: dict = {
            "id": c.id,
            "account_name": c.account_name,
            "account_code": c.account_code,
            "tax_no": c.tax_no,
            "sector": c.sector,
            "financials": {
                "equity": c.equity,
                "annual_net_profit": c.annual_net_profit,
                "liquidity_ratio": c.liquidity_ratio,
                "total_assets": c.total_assets,
                "total_liabilities": c.total_liabilities,
                "sales": c.sales,
                "ebit": c.ebit,
            },
            "latest_request": {
                "amount": latest_request.request_amount,
                "currency": latest_request.currency,
                "date": str(latest_request.request_date),
                "status": latest_request.approval_status,
            } if latest_request else None,
            "latest_score": None,
        }

        if score:
            result["latest_score"] = {
                "final_score": score.final_score,
                "credit_note": score.credit_note,
                "historical_score": score.historical_score,
                "future_score": score.future_score,
                "z_score": score.z_score,
                "z_score_note": score.z_score_note,
                "dscr_score": score.dscr_score,
                "recommended_limit": score.recommended_limit,
                "max_capacity": score.max_capacity,
                "avg_delay_days": score.avg_delay_days,
                "assessment": score.assessment,
                "decision_summary": score.decision_summary,
                "ifrs9_stage": score.ifrs9_stage,
                "ifrs9_pd": score.ifrs9_pd,
                "ifrs9_ecl": score.ifrs9_ecl,
                "calculated_at": str(score.calculated_at),
            }
        return result
    finally:
        session.close()


def _risk_summary(sector: str = "") -> dict:
    session = get_session()
    try:
        q = session.query(CreditScore).join(
            Customer, CreditScore.customer_id == Customer.id
        )
        if sector:
            q = q.filter(Customer.sector.ilike(f"%{sector}%"))

        scores = q.order_by(
            CreditScore.customer_id, CreditScore.calculated_at.desc()
        ).all()

        # Deduplicate — keep latest per customer
        seen: set[int] = set()
        latest: list[CreditScore] = []
        for s in scores:
            if s.customer_id not in seen:
                seen.add(s.customer_id)
                latest.append(s)

        note_dist: dict[str, int] = {}
        stage_dist: dict[str, int] = {}
        total_recommended = 0.0
        total_ecl = 0.0
        score_sum = 0.0

        for s in latest:
            note = s.credit_note or "N/A"
            note_dist[note] = note_dist.get(note, 0) + 1
            stage = str(s.ifrs9_stage) if s.ifrs9_stage else "N/A"
            stage_dist[stage] = stage_dist.get(stage, 0) + 1
            total_recommended += s.recommended_limit or 0.0
            total_ecl += s.ifrs9_ecl or 0.0
            score_sum += s.final_score or 0.0

        n = len(latest) or 1
        return {
            "total_customers_scored": len(latest),
            "avg_final_score": round(score_sum / n, 2),
            "credit_note_distribution": note_dist,
            "ifrs9_stage_distribution": stage_dist,
            "total_recommended_limit_tl": round(total_recommended, 2),
            "total_expected_credit_loss_tl": round(total_ecl, 2),
        }
    finally:
        session.close()


def _score_history(customer_id: int, limit: int = 5) -> list[dict]:
    session = get_session()
    try:
        scores = (
            session.query(CreditScore)
            .filter_by(customer_id=int(customer_id))
            .order_by(CreditScore.calculated_at.desc())
            .limit(min(int(limit), 20))
            .all()
        )
        return [
            {
                "id": s.id,
                "calculated_at": str(s.calculated_at),
                "final_score": s.final_score,
                "credit_note": s.credit_note,
                "recommended_limit": s.recommended_limit,
                "ifrs9_stage": s.ifrs9_stage,
                "ifrs9_pd": s.ifrs9_pd,
                "decision_summary": s.decision_summary,
            }
            for s in scores
        ]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _latest_note(session, customer_id: int) -> str | None:
    score = (
        session.query(CreditScore.credit_note)
        .filter_by(customer_id=customer_id)
        .order_by(CreditScore.calculated_at.desc())
        .first()
    )
    return score[0] if score else None
