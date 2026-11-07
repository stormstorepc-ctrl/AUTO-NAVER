from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dd

import pytest

from app.purchasing.pricing import (ChannelTerms, FxRate, OptionCostInput, SaleTerms, ShippingRateCard,
                                    ValidationError, evaluate_existing_price, quote_price)

NOW = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)


def fx(rate="1", at=NOW):
    return FxRate("CNY", None if rate is None else Dd(rate), at)


def ship(rate="0", at=NOW):
    return ShippingRateCard(None if rate is None else Dd(rate), at, min_billable_g=Dd(1), billing_step_g=Dd(1))


def chan(rp="0.06", rs="0.03", fixed="0", at=NOW):
    return ChannelTerms("smartstore", None if rp is None else Dd(rp), None if rs is None else Dd(rs), Dd(fixed), at)


def opt(price=30000, **kw):
    return OptionCostInput(unit_price=Dd(price), weight_g=kw.pop("weight_g", Dd(100)), **kw)


def test_acceptance_1_free_shipping_example():
    q = quote_price(opt(), fx(), ship(), chan(), SaleTerms(), NOW)
    assert (q.list_price, q.commission_krw, q.profit_krw) == (40600, 2436, 8164)
    assert q.total_cost_krw == 30000 and q.publishable
    assert round(q.margin * 100, 4) == Dd("20.1084")


def test_acceptance_2_separate_shipping_not_double_counted():
    q = quote_price(opt(), fx(), ship(), chan(), SaleTerms(free_shipping=False, customer_shipping_krw=Dd(3000)), NOW)
    assert q.customer_shipping_krw == 3000 and q.total_paid_krw == q.list_price + 3000
    assert q.shipping_fee_krw == 90  # 3000 * 3%
    assert q.profit_krw == q.total_paid_krw - 30000 - q.commission_krw - 90
    assert q.margin >= Dd("0.20")
    free = quote_price(opt(), fx(), ship(), chan(), SaleTerms(), NOW)
    assert q.list_price < free.list_price  # 고객 배송비만큼 상품가 감소


def test_acceptance_3_independent_per_channel_and_option():
    a = quote_price(opt(30000), fx(), ship(), chan("0.06"), SaleTerms(), NOW)
    b = quote_price(opt(30000), fx(), ship(), chan("0.10"), SaleTerms(), NOW)
    c = quote_price(opt(50000), fx(), ship(), chan("0.06"), SaleTerms(), NOW)
    assert len({a.list_price, b.list_price, c.list_price}) == 3
    # 쿠폰 등으로 가격이 내려가 마진 미달이면 탐지
    low = evaluate_existing_price(opt(), fx(), ship(), chan(), SaleTerms(), 36000, NOW)
    assert low.status == "below_target" and not low.publishable


def test_discount_not_double_subtracted():
    q = quote_price(opt(), fx(), ship(), chan(), SaleTerms(seller_discount_rate=Dd("0.10")), NOW)
    assert q.paid_product_krw == round(q.list_price * 0.9)
    assert q.margin >= Dd("0.20") and q.margin < Dd("0.205")  # 과소/과다 보정 없음


@pytest.mark.parametrize("kw", [dict(rate=None), dict(rate="1", at=NOW - timedelta(days=2)), dict(rate="1", at=None)])
def test_acceptance_4_fx_missing_or_stale(kw):
    q = quote_price(opt(), fx(**kw), ship(), chan(), SaleTerms(), NOW)
    assert q.status == "incomplete" and not q.publishable and q.list_price is None and q.blockers


def test_acceptance_4_shipping_weight_fee_missing():
    for o, s, c in [(opt(weight_g=None), ship(), chan()), (opt(), ship(rate=None), chan()),
                    (opt(), ship(at=NOW - timedelta(days=60)), chan()), (opt(), ship(), chan(rp=None)),
                    (opt(), ship(), chan(at=NOW - timedelta(days=60)))]:
        q = quote_price(o, fx(), s, c, SaleTerms(), NOW)
        assert not q.publishable and q.list_price is None


@pytest.mark.parametrize("bad", [
    dict(o=opt(-1)), dict(o=opt(currency="USD")), dict(o=opt(quantity=0)), dict(o=opt(quantity=-3)),
    dict(o=opt(quantity=10**6)), dict(o=opt(quantity=True)), dict(o=opt(quantity=1.5)),
    dict(c=chan(rp="0.85")),                     # 1 - 0.85 - 0.2 <= 0
    dict(c=chan(rp="1.2")), dict(c=chan(fixed="-1")),
    dict(s=SaleTerms(target_margin=Dd("-0.1"))), dict(s=SaleTerms(rounding_unit=0)),
    dict(s=SaleTerms(free_shipping=False, customer_shipping_krw=Dd(-5))),
    dict(s=SaleTerms(free_shipping=False, customer_shipping_krw=Dd(10 ** 9))),  # 음수 상품가
])
def test_acceptance_5_validation_errors(bad):
    with pytest.raises(ValidationError):
        quote_price(bad.get("o", opt()), fx(), ship(), bad.get("c", chan()), bad.get("s", SaleTerms()), NOW)


def test_international_shipping_uses_volumetric_and_min_billing():
    s = ShippingRateCard(Dd(10000), NOW, min_billable_g=Dd(500), billing_step_g=Dd(100))
    light = quote_price(opt(weight_g=Dd(100)), fx(), s, chan(), SaleTerms(), NOW)
    assert light.cost_breakdown["intl_shipping"] == 5000      # 최소 500g
    bulky = OptionCostInput(Dd(1000), weight_g=Dd(100), dims_cm=(Dd(50), Dd(40), Dd(30)))
    q = quote_price(bulky, fx(), s, chan(), SaleTerms(), NOW)
    assert q.cost_breakdown["intl_shipping"] == 120000        # 60000cm3/5000=12kg


def test_scenarios_and_reserve():
    q = quote_price(opt(reserve_rate=Dd("0.02")), fx(), ship(), chan(), SaleTerms(), NOW)
    assert q.cost_breakdown["reserve"] == 600 and q.total_cost_krw == 30600
    assert Dd(q.scenarios["cost+10%"]) < Dd(q.scenarios["cost+5%"]) < q.margin
