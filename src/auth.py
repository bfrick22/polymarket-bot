import logging
import requests
from py_clob_client.client import ClobClient
from config import CLOB_HOST, CHAIN_ID, PRIVATE_KEY, POLY_ADDRESS

logger = logging.getLogger(__name__)


def get_authenticated_client() -> ClobClient:
    """
    Returns a fully authenticated ClobClient ready for trading.

    First run: Creates new L2 API credentials from your L1 private key.
    Subsequent runs: Derives existing credentials (same nonce = same creds).

    IMPORTANT: Store the returned credentials in AWS Secrets Manager,
    not in environment variables, for production.
    """
    if not PRIVATE_KEY:
        raise ValueError("PRIVATE_KEY not set in environment")

    # L1 client — only has private key, can create credentials
    l1_client = ClobClient(
        host=CLOB_HOST,
        chain_id=CHAIN_ID,
        key=PRIVATE_KEY
    )

    # Creates or derives L2 API credentials
    # "Derive" means: same private key + same nonce = same API key every time
    logger.info("Creating/deriving API credentials...")
    creds = l1_client.create_or_derive_api_creds()
    logger.info(f"Got API key: {creds.api_key[:8]}...")

    # L2 client — can trade
    # signature_type=1 = POLY_PROXY (for users who logged in via email/Google on polymarket.com)
    # signature_type=2 = GNOSIS_SAFE (for most users — use this if unsure)
    l2_client = ClobClient(
        host=CLOB_HOST,
        chain_id=CHAIN_ID,
        key=PRIVATE_KEY,
        creds=creds,
        signature_type=2,      # GNOSIS_SAFE — change to 1 if you used email/Google login
        funder=POLY_ADDRESS    # your proxy wallet address from polymarket.com/settings
    )

    return l2_client


def check_geoblock() -> bool:
    """
    Returns True if trading is allowed from current IP.
    CRITICAL: Must return True before placing any orders.
    Remember: US is BLOCKED. Deploy to eu-west-1.
    """
    resp = requests.get("https://polymarket.com/api/geoblock", timeout=10)
    data = resp.json()

    if data["blocked"]:
        logger.error(
            f"GEOBLOCK: Trading blocked from {data['country']}/{data['region']} "
            f"(IP: {data['ip']})"
        )
        return False

    logger.info(f"Geoblock check passed: {data['country']}/{data['region']}")
    return True
