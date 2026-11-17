"""상품 사진을 이 PC에 파일로 저장하고, 네이버 일괄등록용 이미지 묶음(ZIP)을 만든다.

타오바오 상품 페이지는 열지 않는다. 사용자가 확장으로 가져온 사진 주소(타오바오 이미지 서버)만 내려받는다.
네이버 일괄등록 엑셀의 대표이미지·추가이미지 칸은 "업로드한 이미지 파일명"을 받으므로,
파일명을 TB<상품번호>_<순번>.<확장자>로 정하고 같은 이름을 엑셀에 넣는다.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from .pricing import ValidationError

ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = ROOT / "product_images"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_HOST_SUFFIXES = ("alicdn.com", "taobaocdn.com", "tbcdn.cn", "taobao.com", "tmall.com")
# 네이버 이미지 가능 형식: jpg, jpeg, gif, png, bmp (webp 불가)
EXTENSIONS = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/gif": "gif", "image/bmp": "bmp"}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
           "Accept": "image/jpeg,image/png,image/gif;q=0.9,*/*;q=0.5"}
_NAME = re.compile(r"^TB\d{6,20}_\d{2}\.(jpg|png|gif|bmp)$")


def allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in ("http", "https") and any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def file_name(item_id: str, index: int, ext: str) -> str:
    return f"TB{item_id}_{index:02d}.{ext}"


def safe_path(name: str, root: Path | None = None) -> Path:
    """Only names this module creates are served or zipped."""
    if not _NAME.match(name):
        raise ValidationError("잘못된 이미지 파일 이름입니다.")
    return (root or IMAGE_DIR) / name


def _fetch(client, url: str) -> tuple[bytes, str]:
    with client.stream("GET", url, headers=HEADERS) as resp:
        if resp.status_code != 200:
            raise ValidationError(f"이미지 서버 응답 {resp.status_code}")
        if not allowed_url(str(resp.url)):
            raise ValidationError("다른 사이트로 넘어가서 받지 않았습니다.")
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype == "image/webp":
            raise ValidationError("webp 형식이라 네이버에 올릴 수 없습니다.")
        if ctype not in EXTENSIONS:
            raise ValidationError(f"이미지가 아닙니다 ({ctype or '형식 없음'})")
        body = bytearray()
        for chunk in resp.iter_bytes():
            body.extend(chunk)
            if len(body) > MAX_IMAGE_BYTES:
                raise ValidationError("10MB보다 큰 이미지라 받지 않았습니다.")
    if not body:
        raise ValidationError("빈 파일입니다.")
    return bytes(body), EXTENSIONS[ctype]


def save_product_images(store, product: dict, client=None, root: Path | None = None) -> dict:
    """Download every image of the product that is not saved yet. Already saved files are kept as they are."""
    import httpx

    root = root or IMAGE_DIR
    root.mkdir(parents=True, exist_ok=True)
    item_id = product["source_product_id"]
    if not re.fullmatch(r"\d{6,20}", item_id or ""):
        raise ValidationError("타오바오 상품 번호가 없는 상품입니다.")
    own = client is None
    client = client or make_client()
    saved, kept, failed = [], [], []
    try:
        for index, url in enumerate(product["images"], start=1):
            known = store.image_file(url)
            if known and (root / known["name"]).exists():
                kept.append(known["name"])
                continue
            if not allowed_url(url):
                failed.append((url, "타오바오 이미지 서버 주소가 아닙니다."))
                continue
            try:
                data, ext = _fetch(client, url)
            except ValidationError as ex:
                failed.append((url, str(ex)))
                continue
            except httpx.HTTPError as ex:
                failed.append((url, f"받지 못했습니다 ({type(ex).__name__})"))
                continue
            name = file_name(item_id, index, ext)
            (root / name).write_bytes(data)
            store.add_image_file(url, item_id, name, hashlib.sha256(data).hexdigest(), len(data))
            saved.append(name)
    finally:
        if own:
            client.close()
    return {"saved": saved, "kept": kept, "failed": failed, "folder": str(root)}


def make_client():
    import httpx
    return httpx.Client(timeout=20, follow_redirects=True)


def local_names(store, urls: list[str], root: Path | None = None) -> dict[str, str]:
    """url -> saved file name, for files that still exist. Opens its own transaction: call outside store.tx()."""
    root = root or IMAGE_DIR
    out = {}
    for url in urls:
        known = store.image_file(url)
        if known and (root / known["name"]).exists():
            out[url] = known["name"]
    return out


def zip_files(names: list[str], root: Path | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for name in dict.fromkeys(names):
            path = safe_path(name, root)
            if path.exists():
                zf.write(path, arcname=name)
    return buf.getvalue()
