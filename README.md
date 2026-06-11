Project made for assessment for BusinessLabs.org
My id is 2026-2415
**Assessment ID:** 2026-2415
# Customer Support AI Agent
---

## Overview

A Python-based AI customer support agent that handles order lookups, return eligibility checks, refunds, and human escalations. The agent is exposed in two ways:

- **`customersupportagent.py`** — Interactive CLI agent powered by OpenAI GPT-4.1-mini with a tool-calling loop
- **`mcp_server.py`** — The same tools exposed as an MCP (Model Context Protocol) server for Claude Desktop and Claude Code

---

## Features

- Identity verification gate — customers must provide their ID before any order or money operation
- Order lookup and status tracking
- Return eligibility check using per-order return policy (window days + max auto-refund limit)
- Automated refund processing (within policy limits)
- Human escalation with structured ticket for: billing disputes, double charges, subscription changes, order cancellations, wrong item deliveries, and oversized refunds
- Transient error retry logic (up to 3 attempts)
- Customer and order data loaded from `support-tickets (1).json`

---

## Project Structure

```
customersupportagent/
├── customersupportagent.py     # OpenAI CLI agent
├── mcp_server.py               # FastMCP server for Claude Desktop / Claude Code
├── support-tickets (1).json    # Customer, order, and ticket test data
├── .env                        # API keys (not committed)
└── README.md
```

---

## Setup

1. **Install dependencies**
   ```bash
   pip install openai python-dotenv mcp
   ```

2. **Configure API key** — create a `.env` file:
   ```
   OPENAI_API_KEY=your_key_here
   ```

3. **Run the CLI agent**
   ```bash
   python customersupportagent.py
   ```

4. **Run the MCP server** (for Claude Desktop / Claude Code)
   ```bash
   python mcp_server.py
   ```

---

## MCP Integration

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "customer-support": {
      "command": "python",
      "args": ["path/to/mcp_server.py"]
    }
  }
}
```

Or register with Claude Code:
```bash
claude mcp add customer-support -s user -- python "path/to/mcp_server.py"
```

---

## Available Tools

| Tool | Description |
|---|---|
| `get_customer` | Verify customer identity by ID (e.g. CUST-001) |
| `list_customer_orders` | List all orders for the verified customer |
| `lookup_order` | Get status and details for a specific order |
| `check_return_eligibility` | Check return window and refund limit for an order |
| `process_refund` | Process an automated refund within policy limits |
| `escalate_to_human` | Create a structured escalation ticket for a human agent |

---

## Return Policy

Return eligibility is determined per-order based on the policy in effect at purchase time:

- Return windows: 14, 30, 45, or 60 days from purchase date
- Auto-refund limits: $200, $500, $750, or $1000 per order
- Orders exceeding their auto-refund limit are escalated to a human agent
