"""Independent review regression gates for T-COMMERCE-001.

Run from AUTO-NAVER checkout with PYTHONPATH=.: python -m pytest -q this_file.py.
All data and adapters are synthetic; no external service or real account is used.
"""
import threading
from datetime import timedelta

import pytest

from app.purchasing.store import Store
from app.purchasing.workflow import approve, publish, recover_stale_claims
from tests.purchasing.conftest import NOW, prepare, sample


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / 'independent-review.db'))


@pytest.mark.parametrize('changed_field', ['cost', 'translation_source', 'option_identity'])
def test_reapproval_blocks_stale_quote_or_translation(store, changed_field):
    pid = prepare(store, 1)[0]
    changed = sample(0)
    if changed_field == 'cost':
        changed['options'][0]['unit_price'] = '10000'
    elif changed_field == 'translation_source':
        changed['title_src'] = 'A different source product title'
    else:
        # Same option count must not make old option IDs/prices applicable.
        changed['options'][0]['source_option_id'] = 'REPLACEMENT'
    store.upsert_products([changed])

    errors = approve(store, [pid], 'smartstore', 'mock:a1', 'independent-reviewer', NOW)

    assert pid in errors, (
        f'{changed_field}: reapproval must require current source-bound quotes and '
        'reviewed translations; old generation was accepted'
    )


def test_recovery_does_not_repost_while_old_create_can_complete(store):
    pid = prepare(store, 1)[0]
    started = threading.Event()
    release = threading.Event()
    outcomes = []
    worker_errors = []

    class SlowNonIdempotentMock:
        # Deliberately model a server without POST idempotency guarantees.
        is_mock = True

        def __init__(self):
            self.calls = []
            self.remote_objects = []

        def verified(self, channel):
            return True

        def create(self, key, payload):
            ordinal = len(self.calls) + 1
            self.calls.append(key)
            if ordinal == 1:
                started.set()
                if not release.wait(10):
                    raise TimeoutError('synthetic test release missing')
            remote_id = f'SYNTHETIC-{ordinal}'
            self.remote_objects.append(remote_id)
            return remote_id

        def lookup(self, key):
            return self.remote_objects[-1] if self.remote_objects else None

    adapter = SlowNonIdempotentMock()

    def worker():
        try:
            outcomes.append(publish(store, pid, 'smartstore', 'mock:a1', adapter, now=NOW))
        except BaseException as exc:
            worker_errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert started.wait(3)
        # A stale local claim is not proof that the server stopped processing.
        later = NOW + timedelta(minutes=11)
        recovery = recover_stale_claims(store, adapter, now=later)
        second = publish(store, pid, 'smartstore', 'mock:a1', adapter, now=later)
    finally:
        release.set()
        thread.join(5)

    assert not thread.is_alive()
    assert not worker_errors
    assert len(adapter.calls) == 1, (
        f'recovery={recovery}, second={second}, outcomes={outcomes}; '
        'a lookup miss allowed a second POST while the original request could still finish'
    )
    assert len(adapter.remote_objects) == 1


def test_changed_inputs_can_be_reapproved_after_refresh(store):
    from app.purchasing.workflow import MockChannelAdapter, price_product
    from tests.purchasing.conftest import rates
    pid = prepare(store, 1)[0]
    changed = sample(0)
    changed['options'][0]['unit_price'] = '10000'
    changed['title_src'] = 'Updated title'
    store.upsert_products([changed])
    assert pid in approve(store, [pid], 'smartstore', 'mock:a1', 'reviewer', NOW)
    version = store.add_translation(pid, '검수한 새 제목', '수납함', {'A': '흰색', 'B': '검정'})
    store.review_translation(pid, version, 'reviewer')
    price_product(store, pid, 'smartstore', rates(), NOW)
    assert approve(store, [pid], 'smartstore', 'mock:a1', 'reviewer', NOW) == {}
    assert publish(store, pid, 'smartstore', 'mock:a1', MockChannelAdapter(store), now=NOW) == 'published'


@pytest.mark.parametrize('missing', ['china_shipping_krw', 'handling_krw', 'seller_customs_krw',
                                     'domestic_shipping_krw', 'payment_fee_rate', 'reserve_rate'])
def test_missing_imported_cost_is_not_confirmed_zero(store, missing):
    from app.purchasing.workflow import price_product
    from tests.purchasing.conftest import rates
    product = sample(0)
    del product['options'][0][missing]
    store.upsert_products([product])
    quotes = price_product(store, store.list_product_ids()[0], 'smartstore', rates(), NOW)
    assert not quotes[0].publishable
    assert missing in str(quotes[0].blockers)
    assert quotes[1].publishable  # Confirmed zero remains valid for the other option.
