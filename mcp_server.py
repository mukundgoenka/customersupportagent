#!/usr/bin/env python3
"""MCP server — exposes customer support tools to Claude Desktop / Claude Code."""

from mcp.server.fastmcp import FastMCP
from datetime import date
import json
import os
import random
import sys

mcp = FastMCP("customer-support-agent")

_DATA_FILE = os.path.join(os.path.dirname(__file__), "support-tickets (1).json")

def _load_data():
    with open(_DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    customers = {}
    for c in data["customers"]:
        customers[c["id"]] = {
            "name": c["name"],
            "email": c["email"],
            "address": c.get("city", ""),
        }

    orders = {}
    for o in data["orders"]:
        orders[o["orderId"]] = {
            "status": "Delivered",
            "item": o["product"],
            "brand": o.get("brand", ""),
            "purchase_date": o["purchaseDate"],
            "total": o["amount"],
            "customer_id": o["customerId"],
            "refund_policy": {
                "window_days": o["refundPolicy"]["windowDays"],
                "max_auto_refund": o["refundPolicy"]["maxAutoRefund"],
                "policy_version": o["refundPolicy"]["policyVersion"],
            },
        }

    return customers, orders

CUSTOMERS, ORDERS = _load_data()

TODAY = date.today()

# Identity gate: set by get_customer, required before money operations.
_verified_customer_id: str | None = None


def _error(category: str, message: str, retryable: bool = False) -> str:
    return json.dumps({"error": True, "category": category, "isRetryable": retryable, "message": message})


@mcp.tool()
def get_customer(customer_id: str) -> str:
    """Retrieve a customer profile (name, email, address) by CUSTOMER ID like CUST-001.
    Call this first to verify identity before any order lookup or refund operation."""
    global _verified_customer_id
    if random.random() < 0.3:
        return _error("transient", "Customer service temporarily unavailable. Please try again.", retryable=True)
    customer = CUSTOMERS.get(customer_id)
    if customer:
        _verified_customer_id = customer_id
        return json.dumps(customer)
    return _error("validation", f"No customer found with ID '{customer_id}'. Please check the ID and try again.")


@mcp.tool()
def list_customer_orders() -> str:
    """List all orders for the verified customer.
    Use when the customer mentions returning or refunding something but hasn't given a specific order ID,
    or when they own multiple similar items and you need to disambiguate which one they mean."""
    if not _verified_customer_id:
        return _error("permission", "Identity not verified. Ask the customer for their ID (e.g. CUST-001) and call get_customer first.")
    orders = [{"order_id": oid, **o} for oid, o in ORDERS.items() if o["customer_id"] == _verified_customer_id]
    if not orders:
        return _error("validation", f"No orders found for customer '{_verified_customer_id}'.")
    return json.dumps({"orders": orders})


@mcp.tool()
def lookup_order(order_id: str) -> str:
    """Retrieve details for a specific order by ORDER ID like ORD-001-001.
    Use when the customer asks about order status, tracking, or a specific order number."""
    if not _verified_customer_id:
        return _error("permission", "Identity not verified. Ask the customer for their ID (e.g. CUST-001) and call get_customer first.")
    if random.random() < 0.3:
        return _error("transient", "Order service temporarily unavailable. Please try again.", retryable=True)
    order = ORDERS.get(order_id.lstrip("#"))
    if order:
        return json.dumps(order)
    return _error("validation", f"No order found with ID '{order_id}'. Please verify the order number.")


@mcp.tool()
def check_return_eligibility(order_id: str) -> str:
    """Check whether an order is eligible for return based on the return policy attached to that order.
    Always call this before processing any return or refund."""
    if not _verified_customer_id:
        return _error("permission", "Identity not verified. Ask the customer for their ID (e.g. CUST-001) and call get_customer first.")
    order = ORDERS.get(order_id.lstrip("#"))
    if not order:
        return _error("validation", f"No order found with ID '{order_id}'.")

    purchase_date = date.fromisoformat(order["purchase_date"])
    policy = order["refund_policy"]
    window_days = policy["window_days"]
    days_since = (TODAY - purchase_date).days
    days_remaining = window_days - days_since

    if days_remaining > 0:
        return json.dumps({
            "eligible": True,
            "order_id": order_id,
            "item": order["item"],
            "purchase_date": order["purchase_date"],
            "policy_version": policy["policy_version"],
            "return_window_days": window_days,
            "days_remaining": days_remaining,
            "max_auto_refund": policy["max_auto_refund"],
        })
    return json.dumps({
        "eligible": False,
        "order_id": order_id,
        "item": order["item"],
        "purchase_date": order["purchase_date"],
        "policy_version": policy["policy_version"],
        "return_window_days": window_days,
        "days_over_limit": abs(days_remaining),
        "message": (
            f"Return window expired. Policy {policy['policy_version']} allowed "
            f"{window_days} days from purchase; this order is {abs(days_remaining)} day(s) past that limit."
        ),
    })


@mcp.tool()
def process_refund(order_id: str) -> str:
    """Process a refund for an order. Always call check_return_eligibility first.
    Refunds exceeding the order's max_auto_refund limit must be escalated to a human agent."""
    if not _verified_customer_id:
        return _error("permission", "Identity not verified. Ask the customer for their ID (e.g. CUST-001) and call get_customer first.")
    order = ORDERS.get(order_id.lstrip("#"))
    if not order:
        return _error("validation", f"No order found with ID '{order_id}'. Cannot process refund.")

    eligibility = json.loads(check_return_eligibility(order_id))
    if not eligibility.get("eligible"):
        return _error("permission", eligibility.get("message", "Order is not eligible for return."))

    max_auto = order["refund_policy"]["max_auto_refund"]
    if order["total"] > max_auto:
        return _error(
            "permission",
            f"Refund of ${order['total']} exceeds the ${max_auto} automated limit for this order. Escalate to a human agent.",
        )
    return json.dumps({
        "success": True,
        "message": f"Refund of ${order['total']} for order {order_id} processed successfully.",
    })


@mcp.tool()
def escalate_to_human(order_id: str, reason: str, summary: str) -> str:
    """Escalate a case to a human agent.
    Use when: the customer requests a representative; the issue is beyond automated resolution
    (billing disputes, double charges, subscription changes, order cancellations, wrong items delivered);
    or a refund exceeds the order's max_auto_refund limit.
    Populate reason (one sentence) and summary (full context for the human agent)."""
    ticket = (
        f"\n{'='*60}\n"
        f"ESCALATION TICKET\n"
        f"{'='*60}\n"
        f"Order    : #{order_id}\n"
        f"Reason   : {reason}\n"
        f"Summary  :\n{summary}\n"
        f"{'='*60}\n"
    )
    print(ticket, file=sys.stderr)
    return json.dumps({
        "escalated": True,
        "order_id": order_id,
        "reason": reason,
        "summary": summary,
        "message": f"Case for order #{order_id} has been escalated to a human agent. You will be contacted within 24 hours.",
    })


if __name__ == "__main__":
    mcp.run()
