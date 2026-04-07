"""
Look up a Polymarket trader's wallet address by username.

Usage:
    python scripts/lookup_trader.py
    python scripts/lookup_trader.py coldmath
"""

import sys
import json
import requests

GAMMA_HOST = "https://gamma-api.polymarket.com"
DATA_HOST = "https://data-api.polymarket.com"


def lookup_by_gamma_profile(username: str) -> dict | None:
    """
    Search the Gamma API profiles endpoint by username.
    This is the most direct approach — returns wallet address if found.
    """
    print(f"\n[1] Searching Gamma API profiles for '{username}'...")
    resp = requests.get(
        f"{GAMMA_HOST}/profiles",
        params={"username": username},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    print(json.dumps(data, indent=2))
    return data


def lookup_by_leaderboard(username: str) -> None:
    """
    Browse the Data API leaderboard — useful for finding top traders.
    Does not filter by username, so scan the output manually.
    """
    print(f"\n[2] Fetching Data API leaderboard (scan for '{username}')...")
    resp = requests.get(f"{DATA_HOST}/leaderboard", timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # Try to find a matching entry
    matches = []
    entries = data if isinstance(data, list) else data.get("data", [])
    for entry in entries:
        name = (entry.get("name") or entry.get("username") or "").lower()
        if username.lower() in name:
            matches.append(entry)

    if matches:
        print(f"Found {len(matches)} match(es):")
        print(json.dumps(matches, indent=2))
    else:
        print(f"No entries matching '{username}' found in leaderboard.")
        print("Full leaderboard (first 10 entries):")
        print(json.dumps(entries[:10], indent=2))


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "coldmath"
    print(f"Looking up Polymarket trader: {username}")

    try:
        profile = lookup_by_gamma_profile(username)
        address = None
        if isinstance(profile, dict):
            address = profile.get("proxyWallet") or profile.get("address") or profile.get("walletAddress")
        elif isinstance(profile, list) and profile:
            first = profile[0]
            address = first.get("proxyWallet") or first.get("address") or first.get("walletAddress")

        if address:
            print(f"\n✓ Found wallet address: {address}")
            print(f"\nAdd to your .env file:")
            print(f"  TARGET_TRADER={address}")
        else:
            print("\nAddress not found in Gamma profile response. Trying leaderboard...")
            lookup_by_leaderboard(username)

    except requests.RequestException as e:
        print(f"Request failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
