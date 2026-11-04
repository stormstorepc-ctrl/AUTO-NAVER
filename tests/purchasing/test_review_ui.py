"""User-facing flow on a fresh database; all products and channels are synthetic."""
import io
import json
import zipfile

from bs4 import BeautifulSoup
import pytest

from app.purchasing.review_ui import sample_document
from app.purchasing.importer import validate_product
from tests.purchasing.test_web import client, AUTH

ORIGIN = {**AUTH, "Origin": "http://127.0.0.1:8000"}


def form_values(response, action):
    form = BeautifulSoup(response.text, "html.parser").find("form", action=action)
    assert form is not None
    return {field["name"]: field.get("value", "") for field in form.select("input[name]")
            if field.get("type") != "checkbox"}


def import_sample(c):
    response = c.get('/sample.json', headers=AUTH)
    assert response.status_code == 200
    r = c.post('/import', headers=ORIGIN, data={'format': 'json'},
               files={'file': ('demo.json', response.content, 'application/json')})
    assert r.status_code == 200 and '새 상품 1개' in r.text


def ready(c):
    import_sample(c)
    action = '/product/1/price'
    response = c.get('/product/1', headers=AUTH)
    values = form_values(response, action)
    assert values['commission_pct'] == '6.00'
    r = c.post(action, headers=ORIGIN, data={**values, 'rates_confirmed': 'yes'})
    assert r.status_code == 200, r.text
    response = c.get('/product/1', headers=AUTH)
    values = form_values(response, '/product/1/translation')
    r = c.post('/product/1/translation', headers=ORIGIN,
               data={**values, 'title_ko': '시연용 수납함', 'description_ko': '크기 20×10×5cm. 가상 상품입니다.',
                     'option_0': '화이트', 'option_1': '블랙'})
    assert r.status_code == 200, r.text
    response = c.get('/product/1', headers=AUTH)
    values = form_values(response, '/product/1/translation/review')
    r = c.post('/product/1/translation/review', headers=ORIGIN, data={**values, 'confirmed': 'yes'})
    assert r.status_code == 200, r.text


def test_full_review_flow_and_download(store):
    c = client(store)
    assert c.get('/import', headers=AUTH).status_code == 200
    ready(c)
    selected = {'ids': '1', 'channel': 'smartstore', 'account': 'mock:acct1'}
    blocked = c.post('/bulk', headers=ORIGIN, data={**selected, 'action': 'publish'})
    assert '승인 없음' in blocked.text
    assert '승인 1건' in c.post('/bulk', headers=ORIGIN, data={**selected, 'action': 'approve'}).text
    for expected in ('이번 요청 모의 성공 1건', '이미 처리한 상품 1건'):
        r = c.post('/bulk', headers=ORIGIN, data={**selected, 'action': 'publish'})
        assert r.status_code == 200 and expected in r.text and '실제 등록 0건' in r.text
    with store.tx() as db:
        assert db.execute('SELECT COUNT(*) FROM mock_remote').fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM publications WHERE adapter_kind='real'").fetchone()[0] == 0
    r = c.post('/product/1/export', headers=ORIGIN, data={'channel': 'smartstore'})
    assert r.status_code == 200 and r.headers['content-type'] == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        assert archive.read('README.txt').startswith(b'DRAFT')
        assert '시연용 수납함' in archive.read('description.txt').decode()
        assert json.loads(archive.read('draft.json'))['draft'] is True


@pytest.mark.parametrize('path', ['/import', '/product/1/price', '/product/1/translation',
                                  '/product/1/translation/review', '/product/1/export'])
def test_all_new_mutations_require_auth_and_origin(store, path):
    c = client(store)
    assert c.post(path).status_code == 401
    assert c.post(path, headers=AUTH).status_code == 403
    assert c.post(path, headers={**AUTH, 'Origin': 'http://evil.example'}).status_code == 403


def test_invalid_import_and_prices_do_not_mutate(store):
    c = client(store)
    assert c.post('/import', headers=ORIGIN, data={'format': 'json', 'raw': '{'}).status_code == 400
    assert store.list_product_ids() == []
    import_sample(c)
    values = form_values(c.get('/product/1', headers=AUTH), '/product/1/price')
    assert c.post('/product/1/price', headers=ORIGIN, data=values).status_code == 400
    assert c.post('/product/1/price', headers=ORIGIN,
                  data={**values, 'rates_confirmed': 'yes', 'commission_pct': '100'}).status_code == 400
    with store.tx() as db:
        assert store.get_product(db, 1)['version'] == 1
        assert not store.latest_quotes(db, 1, 'smartstore')
    assert c.post('/import', headers=ORIGIN, data={'format': 'json', 'raw': 'a' * (2*1024*1024+1)}).status_code == 413


def test_stale_translation_form_and_review_are_rejected(store):
    c = client(store)
    ready(c)
    old = c.get('/product/1', headers=AUTH)
    values = form_values(old, '/product/1/translation')
    review = form_values(old, '/product/1/translation/review')
    changed = sample_document()['products'][0]
    changed['title_src'] = 'Changed source title'
    store.upsert_products([validate_product(changed)])
    r = c.post('/product/1/translation', headers=ORIGIN,
               data={**values, 'title_ko': '이전 원문 번역', 'description_ko': '이전 설명', 'option_0': '흰색', 'option_1': '검정'})
    assert r.status_code == 400
    assert c.post('/product/1/translation/review', headers=ORIGIN,
                  data={**review, 'confirmed': 'yes'}).status_code == 400


def test_real_accounts_rejected_in_demo_ui(store):
    c = client(store)
    ready(c)
    for action in ('approve', 'publish'):
        assert c.post('/bulk', headers=ORIGIN, data={'ids': '1', 'channel': 'smartstore',
                                                    'account': 'actual-account', 'action': action}).status_code == 400


def test_old_translation_version_not_reviewed(store):
    c = client(store)
    ready(c)
    old = form_values(c.get('/product/1', headers=AUTH), '/product/1/translation/review')
    store.add_translation(1, '새 초안', '새 설명', {'WHITE': '흰색', 'BLACK': '검정'})
    assert c.post('/product/1/translation/review', headers=ORIGIN, data={**old, 'confirmed': 'yes'}).status_code == 400
