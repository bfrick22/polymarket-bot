import logging
import os
import requests
from py_clob_client_v2.client import ClobClient
from config import CLOB_HOST, CHAIN_ID, PRIVATE_KEY, POLY_ADDRESS

logger = logging.getLogger(__name__)

# Polymarket-blocked country codes (ISO 3166-1 alpha-2). US is the primary
# concern; the rest are added as known-blocked regions per Polymarket policy.
BLOCKED_COUNTRY_CODES = {"US"}


def get_authenticated_client() -> ClobClient:
    """
    Returns a fully authenticated ClobClient ready for trading.

    First run: Creates new L2 API credentials from your L1 private key.
    Subsequent runs: Derives existing credentials (same nonce = same creds).
    """
    if not PRIVATE_KEY:
        raise ValueError("PRIVATE_KEY not set in environment")

    l1_client = ClobClient(
        host=CLOB_HOST,
        chain_id=CHAIN_ID,
        key=PRIVATE_KEY,
        signature_type=1,
        funder=POLY_ADDRESS,
    )

    logger.info("Creating/deriving API credentials...")
    creds = l1_client.create_or_derive_api_key()
    logger.info(f"Got API key: {creds.api_key[:8]}...")

    l2_client = ClobClient(
        host=CLOB_HOST,
        chain_id=CHAIN_ID,
        key=PRIVATE_KEY,
        creds=creds,
        signature_type=1,
        funder=POLY_ADDRESS,
    )

    return l2_client


def _try_polymarket_geoblock() -> dict | None:
    """
    Hit Polymarket's official geoblock endpoint. Returns the parsed JSON if
    it actually came back as JSON; returns None if the endpoint is broken
    (currently serves SPA HTML — known Polymarket-side regression as of 2026-06).
    """
    try:
        resp = requests.get(
            "https://polymarket.com/api/geoblock",
            timeout=10,
            headers={"Accept": "application/json"},
        )
    except requests.RequestException as e:
        logger.warning(f"Polymarket geoblock endpoint unreachable: {e}")
        return None

    try:
        return resp.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        ct = resp.headers.get("Content-Type", "?")
        logger.warning(
            f"Polymarket geoblock endpoint returned non-JSON "
            f"(status={resp.status_code}, content-type={ct}). "
            f"Polymarket likely changed this endpoint. Falling back to IP geo lookup."
        )
        return None


def _try_ip_api_fallback() -> dict | None:
    """
    Free IP geolocation lookup via ip-api.com. No API key, no signup.
    Returns {country, countryCode, ip, region}.
    """
    try:
        resp = requests.get("http://ip-api.com/json/", timeout=10)
        data = resp.json()
        if data.get("status") != "success":
            logger.warning(f"ip-api.com fallback failed: {data}")
            return None
        return {
            "country": data.get("country"),
            "countryCode": data.get("countryCode"),
            "region": data.get("regionName"),
            "ip": data.get("query"),
        }
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"ip-api.com fallback failed: {e}")
        return None


def check_geoblock() -> bool:
    """
    Returns True if trading is allowed from current IP. Returns False to
    block trading.

    Resolution order:
      1. SKIP_GEOBLOCK_CHECK=true env var bypasses everything (user takes responsibility)
      2. Polymarket's official /api/geoblock endpoint (currently broken)
      3. Fallback: ip-api.com country lookup against BLOCKED_COUNTRY_CODES
      4. If all checks fail and no override → refuse to start (fail-safe)
    """
    if os.getenv("SKIP_GEOBLOCK_CHECK", "").lower() in ("1", "true", "yes"):
        logger.warning("SKIP_GEOBLOCK_CHECK=true — geoblock validation bypassed by env var")
        return True

    # 1. Official Polymarket endpoint
    pm_data = _try_polymarket_geoblock()
    if pm_data is not None and "blocked" in pm_data:
        if pm_data["blocked"]:
            logger.error(
                f"GEOBLOCK: Trading blocked from "
                f"{pm_data.get('country','?')}/{pm_data.get('region','?')} "
                f"(IP: {pm_data.get('ip','?')})"
            )
            return False
        logger.info(
            f"Geoblock check passed (Polymarket): "
            f"{pm_data.get('country','?')}/{pm_data.get('region','?')}"
        )
        return True

    # 2. Fallback IP geo lookup
    geo = _try_ip_api_fallback()
    if geo is None:
        logger.error(
            "Could not verify geoblock status from any source. "
            "Refusing to start. To override, set SKIP_GEOBLOCK_CHECK=true."
        )
        return False

    cc = (geo.get("countryCode") or "").upper()
    if cc in BLOCKED_COUNTRY_CODES:
        logger.error(
            f"GEOBLOCK: IP geolocates to {geo.get('country')}/{geo.get('region')} "
            f"(IP: {geo.get('ip')}) which is in the blocked list {BLOCKED_COUNTRY_CODES}"
        )
        return False

    logger.info(
        f"Geoblock check passed (ip-api fallback): "
        f"{geo.get('country')}/{geo.get('region')} (IP: {geo.get('ip')})"
    )
    return True
