from openai import OpenAI
from dotenv import load_dotenv
from datetime import date
import json
import os
import random

load_dotenv()

client = OpenAI()

tools = [
    {"type": "function", "function": {
        "name": "get_customer",
        "description": (
            "Retrieves a customer's profile (name, email, address) given a CUSTOMER ID like CUST-001. "
            "Use ONLY when the user gives a customer ID or asks about their own profile. "
            "DO NOT use for order lookups — use lookup_order instead."
        ),
        "parameters": {"type": "object", "properties": {
            "customer_id": {"type": "string", "description": "e.g. CUST-001"}
        }, "required": ["customer_id"]},
    }},
    {"type": "function", "function": {
        "name": "list_customer_orders",
        "description": (
            "Lists all orders belonging to the verified customer. "
            "Use this when the customer mentions returning or refunding a product but hasn't given a specific order ID, "
            "or when they own multiple similar items and you need to disambiguate which one they mean."
        ),
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "lookup_order",
        "description": (
            "Retrieves details for a specific order given an ORDER ID like ORD-001-001. "
            "Use when the user asks 'where is my order', 'order status', 'track ORD-###', etc."
        ),
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string", "description": "e.g. ORD-001-001"}
        }, "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "check_return_eligibility",
        "description": (
            "Checks whether a specific order is eligible for return based on the return policy "
            "attached to that order at the time of purchase. Call this before processing any return or refund."
        ),
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string", "description": "e.g. ORD-001-001"}
        }, "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "process_refund",
        "description": (
            "Processes a refund for a given ORDER ID. "
            "Always call check_return_eligibility first. "
            "Refunds exceeding the order's max_auto_refund limit will be blocked and must be escalated."
        ),
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string", "description": "e.g. ORD-001-001"}
        }, "required": ["order_id"]},
    }},
    {"type": "function", "function": {
        "name": "escalate_to_human",
        "description": (
            "Escalates a case to a human agent. "
            "Use when: the user asks to speak with a representative; the issue is beyond automated resolution "
            "(billing disputes, double charges, subscription changes, order cancellations, wrong items delivered); "
            "or a refund exceeds the order's max_auto_refund limit. "
            "You MUST populate 'reason' and 'summary' so the human agent has full context."
        ),
        "parameters": {"type": "object", "properties": {
            "order_id": {"type": "string", "description": "The order ID this case is about, e.g. ORD-001-001"},
            "reason":   {"type": "string", "description": "One sentence: why automated resolution failed."},
            "summary":  {"type": "string", "description": (
                "Structured recap for the human agent: "
                "customer identity, items involved, what was tried, what the customer wants, and the blocking reason."
            )},
        }, "required": ["order_id", "reason", "summary"]},
    }}
]

# Load customer and order data from the support tickets JSON file
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

MAX_RETRIES = 3
TODAY = date.today()


def _error(category, message, retryable=False):
    return json.dumps({
        "error": True,
        "category": category,
        "isRetryable": retryable,
        "message": message,
    })


def get_customer(customer_id):
    if random.random() < 0.3:
        return _error("transient", "Customer service temporarily unavailable. Please try again.", retryable=True)
    customer = CUSTOMERS.get(customer_id)
    if customer:
        return json.dumps(customer)
    return _error("validation", f"No customer found with ID '{customer_id}'. Please check the ID and try again.")


def list_customer_orders(customer_id):
    orders = [
        {"order_id": oid, **o}
        for oid, o in ORDERS.items()
        if o["customer_id"] == customer_id
    ]
    if not orders:
        return _error("validation", f"No orders found for customer '{customer_id}'.")
    return json.dumps({"orders": orders})


def lookup_order(order_id):
    if random.random() < 0.3:
        return _error("transient", "Order service temporarily unavailable. Please try again.", retryable=True)
    order = ORDERS.get(order_id.lstrip("#"))
    if order:
        return json.dumps(order)
    return _error("validation", f"No order found with ID '{order_id}'. Please verify the order number.")


def check_return_eligibility(order_id):
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


def process_refund(order_id):
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
            f"Refund of ${order['total']} exceeds the ${max_auto} automated limit for this order. This must be handled by a human agent.",
        )
    return json.dumps({"success": True, "message": f"Refund of ${order['total']} for order {order_id} processed successfully."})


def escalate_to_human(order_id, reason, summary):
    print("\n" + "="*60)
    print("ESCALATION TICKET")
    print("="*60)
    print(f"Order    : #{order_id}")
    print(f"Reason   : {reason}")
    print(f"Summary  :\n{summary}")
    print("="*60 + "\n")
    return json.dumps({
        "escalated": True,
        "order_id": order_id,
        "reason": reason,
        "summary": summary,
        "message": f"Case for order #{order_id} has been escalated to a human agent with a full summary. You will be contacted within 24 hours.",
    })


messages = [{"role": "system", "content": (
    "You are a helpful customer support agent. Use the provided tools to assist customers.\n\n"
    "IDENTITY: Always call get_customer with the customer's ID (e.g. CUST-001) before any order or refund operation.\n\n"
    "RETURNS & REFUNDS:\n"
    "- When a customer wants to return or refund something and hasn't specified which order, "
    "call list_customer_orders to show their purchases and ask them to confirm which item they mean.\n"
    "- Always call check_return_eligibility before processing any return or refund.\n"
    "- Each order has its own max_auto_refund limit (visible in check_return_eligibility output). "
    "If the order total exceeds that limit, call process_refund — it will block and instruct you to escalate.\n\n"
    "ESCALATE IMMEDIATELY (do not attempt automated resolution) for:\n"
    "- Double/incorrect charges on a credit card or bank account\n"
    "- Subscription plan changes or upgrades\n"
    "- Billing questions or invoice disputes\n"
    "- Order cancellations\n"
    "- Wrong item delivered (exchange or replacement requests)\n"
    "- Any request to speak with a human representative\n\n"
    "ESCALATION QUALITY: When escalating, you MUST provide a concise 'reason' (one sentence) and a structured "
    "'summary' covering: customer identity, items discussed, what was attempted, what the customer wants, and why "
    "it could not be resolved automatically."
)}]

verified_customer_id = None

user_input = input("You: ")
messages.append({"role": "user", "content": user_input})

while True:
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        max_tokens=1024,
        tools=tools,
        messages=messages,
    )

    print("finish_reason:", response.choices[0].finish_reason)

    if response.choices[0].finish_reason == "stop":
        print("Agent:", response.choices[0].message.content)
        messages.append(response.choices[0].message)
        user_input = input("You: ")
        if user_input.lower() in ("exit", "quit"):
            break
        messages.append({"role": "user", "content": user_input})

    if response.choices[0].finish_reason == "tool_calls":
        messages.append(response.choices[0].message)
        tool_results = []

        for tool_call in response.choices[0].message.tool_calls:
            args = json.loads(tool_call.function.arguments)
            name = tool_call.function.name
            result = _error("transient", "Max retries exceeded. Please try again later.")

            for attempt in range(1, MAX_RETRIES + 1):
                if name == "get_customer":
                    raw = get_customer(args["customer_id"])
                    parsed = json.loads(raw)
                    if not parsed.get("error"):
                        verified_customer_id = args["customer_id"]

                elif name == "list_customer_orders":
                    if not verified_customer_id:
                        raw = _error("permission", "Identity not verified. Ask the user for their customer ID (e.g. CUST-001) and call get_customer first.")
                    else:
                        raw = list_customer_orders(verified_customer_id)

                elif name == "lookup_order":
                    if not verified_customer_id:
                        raw = _error("permission", "Identity not verified. Ask the user for their customer ID (e.g. CUST-001) and call get_customer first.")
                    else:
                        raw = lookup_order(args["order_id"])

                elif name == "check_return_eligibility":
                    if not verified_customer_id:
                        raw = _error("permission", "Identity not verified. Ask the user for their customer ID (e.g. CUST-001) and call get_customer first.")
                    else:
                        raw = check_return_eligibility(args["order_id"])

                elif name == "process_refund":
                    if not verified_customer_id:
                        raw = _error("permission", "Identity not verified. Ask the user for their customer ID (e.g. CUST-001) and call get_customer first.")
                    else:
                        raw = process_refund(args["order_id"])

                elif name == "escalate_to_human":
                    raw = escalate_to_human(args["order_id"], args["reason"], args["summary"])

                else:
                    raw = _error("validation", f"Unknown tool: {name}")

                parsed = json.loads(raw)
                if parsed.get("isRetryable") and attempt < MAX_RETRIES:
                    print(f"  Transient error on '{name}', retrying (attempt {attempt}/{MAX_RETRIES})...")
                    continue

                result = raw
                break

            print(f"Tool ran: {name}({args}) -> {result}")
            tool_results.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "content": result,
            })

        messages.extend(tool_results)
