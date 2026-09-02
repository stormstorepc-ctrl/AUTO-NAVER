import base64
import time
from typing import Any

import bcrypt
import httpx

from .models import Product
from .settings import settings

TOKEN_URL = "https://api.commerce.naver.com/external/v1/oauth2/token"
API_BASE = "https://api.commerce.naver.com/external"


def signature(client_id: str, client_secret: str, timestamp_ms: int) -> str:
    password = f"{client_id}_{timestamp_ms}".encode("utf-8")
    hashed = bcrypt.hashpw(password, client_secret.encode("utf-8"))
    return base64.urlsafe_b64encode(hashed).decode("utf-8")


class NaverCommerceClient:
    def __init__(self) -> None:
        self.client_id = settings.naver_commerce_client_id
        self.client_secret = settings.naver_commerce_client_secret
        self.account_id = settings.naver_commerce_account_id
        self._access_token = ""
        self._expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.account_id)

    def token(self, force: bool = False) -> str:
        if not self.configured:
            raise RuntimeError("네이버 커머스 API 환경변수가 설정되지 않았습니다.")
        if self._access_token and not force and time.time() < self._expires_at - 120:
            return self._access_token
        ts = int(time.time() * 1000)
        data = {
            "client_id": self.client_id,
            "timestamp": str(ts),
            "client_secret_sign": signature(self.client_id, self.client_secret, ts),
            "grant_type": "client_credentials",
            "type": "SELLER",
            "account_id": self.account_id,
        }
        with httpx.Client(timeout=30) as client:
            response = client.post(TOKEN_URL, data=data)
            response.raise_for_status()
            payload = response.json()
        self._access_token = payload["access_token"]
        self._expires_at = time.time() + int(payload.get("expires_in", 10800))
        return self._access_token

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {self.token()}"
        headers.setdefault("Content-Type", "application/json")
        with httpx.Client(base_url=API_BASE, timeout=60) as client:
            response = client.request(method, path, headers=headers, **kwargs)
            if response.status_code == 401:
                headers["Authorization"] = f"Bearer {self.token(force=True)}"
                response = client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response

    def build_product_payload(self, product: Product) -> dict[str, Any]:
        if not product.category:
            raise ValueError("네이버 카테고리 ID가 상품에 설정되지 않았습니다.")
        if not product.representative_image:
            raise ValueError("대표 이미지 URL이 없습니다.")
        if not product.sale_price or product.sale_price < 0:
            raise ValueError("판매가가 올바르지 않습니다.")
        if product.status == "SOLD_OUT" or product.stock <= 0:
            raise ValueError("품절 상품은 신규 등록할 수 없습니다.")

        # 실제 스토어의 고시정보/배송정책 필수값을 설정으로 분리한다.
        # product.category는 우선 네이버 카테고리 ID 문자열로 사용한다.
        category_id = product.category
        return {
            "originProduct": {
                "statusType": "SALE",
                "saleType": "NEW",
                "name": product.name,
                "leafCategoryId": category_id,
                "detailContent": product.detail_html or f"<p>{product.name}</p>",
                "images": {"representativeImage": {"url": product.representative_image}},
                "salePrice": product.sale_price,
                "stockQuantity": product.stock,
            }
        }

    def register_product(self, product: Product) -> str:
        payload = self.build_product_payload(product)
        response = self.request("POST", "/v2/products", json=payload)
        data = response.json()
        # API 응답 구조 변화에 대비해 여러 키를 지원한다.
        product_no = data.get("originProductNo") or data.get("productNo")
        if not product_no:
            raise RuntimeError(f"상품 등록 응답에서 상품번호를 찾을 수 없습니다: {data}")
        return str(product_no)

    def update_origin_product(self, origin_product_no: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.request("PUT", f"/v2/products/origin-products/{origin_product_no}", json=payload)
        return response.json()


naver_commerce = NaverCommerceClient()
