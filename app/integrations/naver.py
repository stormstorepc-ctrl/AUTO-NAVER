import time
import base64
import bcrypt
import httpx
from . import __name__ as _pkg
from ..settings import settings

TOKEN_URL = 'https://api.commerce.naver.com/external/v1/oauth2/token'
PRODUCT_URL = 'https://api.commerce.naver.com/external/v2/products'

def commerce_signature(client_id: str, client_secret: str, timestamp_ms: int) -> str:
    password = f'{client_id}_{timestamp_ms}'.encode()
    hashed = bcrypt.hashpw(password, client_secret.encode())
    return base64.urlsafe_b64encode(hashed).decode()

async def issue_seller_token(account_id: str | None = None) -> dict:
    cid = settings.naver_commerce_client_id
    secret = settings.naver_commerce_client_secret
    account_id = account_id or settings.naver_commerce_account_id
    if not cid or not secret or not account_id:
        raise RuntimeError('NAVER_COMMERCE_CLIENT_ID/SECRET/ACCOUNT_ID 설정이 필요합니다.')
    ts = int(time.time() * 1000)
    data = {
        'client_id': cid,
        'timestamp': str(ts),
        'client_secret_sign': commerce_signature(cid, secret, ts),
        'grant_type': 'client_credentials',
        'type': 'SELLER',
        'account_id': account_id,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(TOKEN_URL, data=data)
        r.raise_for_status()
        return r.json()

async def create_product(payload: dict, account_id: str | None = None) -> dict:
    token = await issue_seller_token(account_id)
    access = token.get('access_token')
    if not access:
        raise RuntimeError(f'네이버 토큰 발급 실패: {token}')
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(PRODUCT_URL, json=payload, headers={'Authorization': f'Bearer {access}'})
        if r.status_code >= 400:
            raise RuntimeError(f'Commerce API {r.status_code}: {r.text[:1000]}')
        return r.json()
