import threading
from datetime import timedelta
from decimal import Decimal as Dd

import pytest

from app.purchasing.pricing import ValidationError
from app.purchasing.workflow import (MockChannelAdapter, approve, blockers_before_approval, export_draft, exclude,
                                     price_product, publish, recover_stale_claims, run_week, idem_key)
from tests.purchasing.conftest import CH, NOW, prepare, rates, sample


def jobs(ids, channels=("smartstore",), acct="mock:a1"):
    return [(i, ch, acct) for i in ids for ch in channels]


def test_approved_publishes_once_mock_only(store):
    ids = prepare(store, 1)
    ad = MockChannelAdapter(store)
    assert publish(store, ids[0], "smartstore", "mock:a1", ad, now=NOW) == "published"
    s = run_week(store, "2026-W45", jobs(ids), ad, NOW)
    assert s["mock_published"] == 1 and s["real_published"] == 0 and s["outcomes"] == {"skipped": 1}


def test_7_unapproved_unverified_missing_evidence_margin_never_create_request(store):
    ids = prepare(store, 4, approve_them=False)
    ad = MockChannelAdapter(store)
    assert publish(store, ids[0], "smartstore", "mock:a1", ad, now=NOW).startswith("blocked:") and "승인 없음" in publish(store, ids[0], "smartstore", "mock:a1", ad, now=NOW)
    # 근거 누락 / 제외 카테고리
    store.upsert_products([sample(1, compliance={"sale_allowed_confirmed": False, "restricted_flags": []}),
                           sample(2, compliance={"sale_allowed_confirmed": True, "restricted_flags": ["battery"]})])
    assert approve(store, [ids[1], ids[2]], "smartstore", "mock:a1", "t", NOW).keys() == {ids[1], ids[2]}
    # 미검증 실채널
    from app.purchasing.workflow import BlockedRealAdapter
    assert approve(store, [ids[0]], "smartstore", "acct", "t", NOW) == {}
    r = publish(store, ids[0], "smartstore", "acct", BlockedRealAdapter(), now=NOW)
    assert r.startswith("blocked:") and "미검증" in r
    # 실채널 blocked 는 게시 행/시도를 만들지 않고 mock POST 도 없다
    with store.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM publish_attempts").fetchone()[0] == 0
    assert ad.create_calls == []


def test_margin_below_target_cannot_be_approved(store):
    ids = prepare(store, 1, approve_them=False)
    with store.tx() as c:   # 견적 결과를 마진 미달로 변조
        import json
        r = json.loads(c.execute("SELECT result FROM quotes LIMIT 1").fetchone()[0]); r["margin"] = "0.10"
        c.execute("UPDATE quotes SET result=?", (json.dumps(r),))
    assert "마진 미달" in str(approve(store, ids, "smartstore", "mock:a1", "t", NOW))


def test_6_changes_after_approval_invalidate(store):
    ad = MockChannelAdapter(store)
    for change in ("cost", "translation", "image", "rate"):
        ids = prepare(store, 1)
        pid = ids[0]
        if change == "cost":
            store.upsert_products([sample(0, options=[{"source_option_id": "A", "name": "白色", "unit_price": "999", "weight_g": "300"},
                                                      {"source_option_id": "B", "name": "黑色", "unit_price": "120", "weight_g": "350"}])])
            price_product(store, pid, "smartstore", rates(), NOW)
        elif change == "translation":
            store.add_translation(pid, "다른 제목", "다른 설명", {"A": "a", "B": "b"}, reviewed=True)
        elif change == "image":
            store.upsert_products([sample(0, images=["https://img.example.com/other.jpg"])])
        else:
            from app.purchasing.pricing import FxRate
            rb = rates(); rb.fx = FxRate("CNY", Dd("200"), NOW)
            price_product(store, pid, "smartstore", rb, NOW)
        r = publish(store, pid, "smartstore", "mock:a1", ad, now=NOW)
        assert r.startswith("blocked:") and ("내용 변경" in r or "번역" in r or "견적" in r), (change, r)
        store.upsert_products([sample(0)])   # 원복 후 다음 케이스를 위해 초기화
        with store.tx() as c:
            c.execute("DELETE FROM approvals"); c.execute("DELETE FROM quotes"); c.execute("DELETE FROM translations")
    assert ad.create_calls == []


def test_6_approval_expiry(store):
    ids = prepare(store, 1)
    ad = MockChannelAdapter(store)
    r = publish(store, ids[0], "smartstore", "mock:a1", ad, now=NOW + timedelta(hours=25))
    assert r.startswith("blocked:") and "승인 만료" in r and ad.create_calls == []


def test_4_expired_rates_block(store):
    ids = prepare(store, 1, approve_them=False)
    assert "견적 입력 만료" in str(approve(store, ids, "smartstore", "mock:a1", "t", NOW + timedelta(hours=30)))


def test_8_no_duplicate_same_week_or_next_week(store):
    ids = prepare(store, 5)
    ad = MockChannelAdapter(store)
    run_week(store, "2026-W45", jobs(ids), ad, NOW)
    s2 = run_week(store, "2026-W46", jobs(ids), ad, NOW)
    assert len(ad.create_calls) == 5 and len(set(ad.create_calls)) == 5
    assert s2["outcomes"] == {"skipped": 5} and s2["mock_published"] == 5


def test_9_lost_response_is_unknown_and_never_reposted(store):
    ids = prepare(store, 2)
    with store.tx() as c:
        p = store.get_product(c, ids[0])
    key = idem_key(p, "smartstore", "mock:a1")
    ad = MockChannelAdapter(store, {key: "lose_response"})
    assert publish(store, ids[0], "smartstore", "mock:a1", ad, now=NOW) == "unknown"
    for _ in range(3):   # 재실행해도 POST 재시도 없음
        assert publish(store, ids[0], "smartstore", "mock:a1", ad, now=NOW) == "skipped:unknown"
    assert ad.create_calls.count(key) == 1
    s = run_week(store, "w", jobs(ids), ad, NOW)
    assert s["unknown"] == 1 and s["mock_published"] == 1 and s["real_published"] == 0
    assert recover_stale_claims(store, ad, now=NOW)["published"] == 1     # 조회로 등록 확인
    assert run_week(store, "w2", jobs(ids), ad, NOW)["mock_published"] == 2


def test_9_rejected_retry_allowed_but_absent_confirmed_only_via_lookup(store):
    ids = prepare(store, 1)
    with store.tx() as c:
        key = idem_key(store.get_product(c, ids[0]), "smartstore", "mock:a1")
    ad = MockChannelAdapter(store, {key: "reject"})
    assert publish(store, ids[0], "smartstore", "mock:a1", ad, now=NOW) == "failed"
    ad.behavior.clear()
    assert publish(store, ids[0], "smartstore", "mock:a1", ad, now=NOW) == "published"


def test_10_13_crash_midway_then_restart_preserves_results(store):
    ids = prepare(store, 10)
    with store.tx() as c:
        key = idem_key(store.get_product(c, ids[4]), "smartstore", "mock:a1")
    ad = MockChannelAdapter(store, {key: "crash"})
    with pytest.raises(KeyboardInterrupt):
        run_week(store, "W", jobs(ids), ad, NOW)
    ad2 = MockChannelAdapter(store)          # 프로세스 재시작
    # 강제 종료로 claimed 상태가 남음 -> 일정 시간 후 조회로 정리, POST 재시도 없음
    assert recover_stale_claims(store, ad2, older_than=timedelta(0), now=NOW)["published"] == 1  # mock 원격엔 이미 있음
    s = run_week(store, "W", jobs(ids), ad2, NOW)
    assert s["mock_published"] == 10 and s["real_published"] == 0
    assert len(ad2.create_calls) == 5        # 앞서 완료된 4건 + 복구된 1건은 재요청하지 않음 (나머지 5건만)


def test_10_full_scale_100_products_3_channels(store):
    ids = prepare(store, 100, channels=CH)
    ad = MockChannelAdapter(store)
    s = run_week(store, "2026-W45", jobs(ids, CH), ad, NOW)
    assert s["jobs"] == 300 and s["mock_published"] == 300 and s["real_published"] == 0 and s["unknown"] == 0
    assert len(set(ad.create_calls)) == len(ad.create_calls) == 300
    assert run_week(store, "2026-W46", jobs(ids, CH), ad, NOW)["outcomes"] == {"skipped": 300}


def test_11_fewer_than_100_reports_actual_count(store):
    ids = prepare(store, 7, approve_them=False)
    store.upsert_products([sample(i, compliance={"sale_allowed_confirmed": False, "restricted_flags": []}) for i in (0, 1)])
    failed = approve(store, ids, "smartstore", "mock:a1", "t", NOW)
    assert set(failed) == {ids[0], ids[1]} and len(ids) - len(failed) == 5   # 허위 보충 없음
    assert all("판매 가능 근거" in failed[i][0] for i in failed)


def test_bulk_limit_100(store):
    with pytest.raises(ValidationError):
        approve(store, list(range(101)), "smartstore", "mock:a1", "t", NOW)


def test_14_concurrent_publish_only_one_post(store):
    ids = prepare(store, 1)
    ad = MockChannelAdapter(store)
    res = []
    barrier = threading.Barrier(8)

    def work():
        barrier.wait()
        res.append(publish(store, ids[0], "smartstore", "mock:a1", ad, now=NOW))
    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert res.count("published") == 1 and len(ad.create_calls) == 1
    assert all(r == "published" or r.startswith("skipped:") for r in res)


def test_14_price_change_right_after_approval_blocks(store):
    ids = prepare(store, 1)
    from app.purchasing.pricing import FxRate
    rb = rates(); rb.fx = FxRate("CNY", Dd("191"), NOW)
    price_product(store, ids[0], "smartstore", rb, NOW)
    ad = MockChannelAdapter(store)
    assert "내용 변경" in publish(store, ids[0], "smartstore", "mock:a1", ad, now=NOW) and ad.create_calls == []


def test_mock_adapter_refuses_non_mock_account(store):
    ids = prepare(store, 1, account="real-account")
    ad = MockChannelAdapter(store)
    assert "mock:" in publish(store, ids[0], "smartstore", "real-account", ad, now=NOW)


def test_excluded_product_cannot_publish(store):
    ids = prepare(store, 1)
    exclude(store, ids, "t", "테스트")
    assert publish(store, ids[0], "smartstore", "mock:a1", MockChannelAdapter(store), now=NOW).startswith("blocked:")


def test_13_audit_log_redacts_secrets(store):
    with store.tx() as c:
        store.audit(c, "t", "x", {"password": "hunter2", "api_key": "k", "ok": 1, "nested": {"cookie": "c"}})
        d = c.execute("SELECT detail FROM audit ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert "hunter2" not in d and '"ok":1' in d and '"c"' not in d


def test_export_draft_package(store, tmp_path):
    ids = prepare(store, 1)
    store.upsert_products([sample(0)])
    d = export_draft(store, ids[0], "smartstore", tmp_path / "out")
    assert (d / "README.txt").read_text(encoding="utf-8").startswith("DRAFT")
    assert {f.name for f in d.iterdir()} == {"README.txt", "description.txt", "images.txt", "options.csv", "draft.json"}
    with store.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == 0   # 내보내기는 게시 아님
