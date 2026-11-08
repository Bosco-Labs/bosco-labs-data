"""check_vendor as a tool for Claude (Anthropic Python SDK, manual tool-use loop).

pip install anthropic   # plus this project: pip install -e .
export ANTHROPIC_API_KEY=...   # BOSCO_API_KEY optional: without it the free lookups run
python examples/claude_tool_use.py "Can we onboard Novo Nordisk A/S (Denmark) as a supplier?"
"""

import json
import sys

import anthropic
from vendor_check import VendorCheckError, check_vendor

TOOLS = [
    {
        "name": "check_vendor",
        "description": (
            "KYB screening of one company from official registers (Bosco Labs): register status, "
            "LEI, insolvency, recent accounts, sanctions, VAT, IBAN; each check is pass, fail, "
            "review or unverified with a source link. 'unverified' means not checked, never safe. "
            "Without an API key it returns free LEI candidates and the price of the full check."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Company name or identifier (LEI, CVR)"},
                "country": {"type": "string", "description": "ISO 2-letter code, e.g. DK"},
                "vat_number": {"type": "string", "description": "VAT number, e.g. DK24256790"},
                "iban": {"type": "string", "description": "IBAN the vendor wants to be paid on"},
            },
            "required": ["name"],
        },
    }
]


def run_tool(args: dict) -> tuple[str, bool]:
    try:
        return json.dumps(check_vendor(**args), ensure_ascii=False), False
    except (VendorCheckError, TypeError) as e:
        return f"Error: {e}", True


def main(question: str) -> None:
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    while True:
        response = client.messages.create(
            model="claude-opus-5-5",
            max_tokens=16000,
            system="You screen suppliers. Cite the source link of every check you mention.",
            tools=TOOLS,
            messages=messages,
        )
        if response.stop_reason != "tool_use":  # end_turn, max_tokens or refusal
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                text, failed = run_tool(block.input)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": text,
                        "is_error": failed,
                    }
                )
        messages.append({"role": "user", "content": results})
    print("".join(b.text for b in response.content if b.type == "text"))


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]) or "Can we onboard Novo Nordisk A/S (Denmark) as a supplier?")
