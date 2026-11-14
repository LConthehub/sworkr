"""
Currencies. Every amount sworkr stores has a currency code next to it (the `currency` columns).

Only USD is switched on for now. To add another currency later:
1. Add it to SUPPORTED below (and to CURRENCIES in frontend/src/colors.js, which formats amounts).
2. Decide how totals that mix currencies are shown (convert at a rate, or total each currency separately).
   Until that's decided, everything is assumed to be in one currency, which `check` guarantees.
"""

from fastapi import HTTPException

DEFAULT = "USD"
SUPPORTED = {
    "USD": {"symbol": "$", "decimals": 2, "name": "US dollar"},
}


def check(code: str) -> str:
    """The currency code, upper-cased, or a 400 if it isn't one sworkr supports yet."""
    code = (code or DEFAULT).strip().upper()
    if code not in SUPPORTED:
        raise HTTPException(status_code=400, detail=f"Only {', '.join(SUPPORTED)} is supported for now")
    return code
