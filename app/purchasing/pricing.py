"""Decimal 기반 채널·옵션별 가격 엔진 (구매대행 1단계).

예상 공헌이익률 = (고객 실결제액 - 총원가 - 판매수수료 - 고정수수료) / 고객 실결제액
고정비·소득세 차감 전 값이며 순이익을 보장하지 않는다.
원단위 규칙: 수수료는 건별로 원 단위 반올림(ROUND_HALF_UP), 원가 항목은 원 단위 올림(ROUND_CEILING),
판매가는 rounding_unit(기본 100원) 단위 올림 후 마진을 재검산하고 미달이면 한 단위씩 올린다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, InvalidOperation
from typing import Any

ZERO = Decimal(0)
ONE = Decimal(1)
SUPPORTED_SOURCE_CURRENCIES = {"CNY"}
MAX_QUANTITY = 1000


class ValidationError(ValueError):
    """입력값이 잘못된 경우 (음수, 잘못된 통화, 분모 0 이하 등)."""


def D(value: Any, name: str = "value") -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValidationError(f"{name}: 숫자가 아닙니다 ({value!r})")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{name}: 숫자가 아닙니다 ({value!r})")
    if not d.is_finite():
        raise ValidationError(f"{name}: 유한한 숫자여야 합니다")
    return d


def _nonneg(value: Any, name: str) -> Decimal:
    d = D(value, name)
    if d < 0:
        raise ValidationError(f"{name}: 음수일 수 없습니다 ({d})")
    return d


def _rate(value: Any, name: str) -> Decimal:
    d = D(value, name)
    if d < 0 or d >= 1:
        raise ValidationError(f"{name}: 0 이상 1 미만의 비율이어야 합니다 ({d})")
    return d


def won_ceil(x: Decimal) -> Decimal:
    return x.to_integral_value(rounding=ROUND_CEILING)


def won_half_up(x: Decimal) -> Decimal:
    return x.quantize(ONE, rounding=ROUND_HALF_UP)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class FxRate:
    currency: str
    krw_per_unit: Decimal | None
    observed_at: datetime | None
    source: str = ""


@dataclass(frozen=True)
class ShippingRateCard:
    """국제배송(배대지) 요율. 모든 값이 있어야 가격이 확정된다."""
    rate_per_kg: Decimal | None
    observed_at: datetime | None
    min_billable_g: Decimal = Decimal(500)
    billing_step_g: Decimal = Decimal(100)
    volumetric_divisor: Decimal = Decimal(5000)  # cm^3 / divisor = kg
    source: str = ""


@dataclass(frozen=True)
class ChannelTerms:
    channel: str
    commission_rate: Decimal | None          # 상품 판매수수료율 rp
    shipping_fee_rate: Decimal | None        # 배송비 수수료율 rs (별도 배송비일 때)
    fixed_fee: Decimal = ZERO                # 건당 고정 수수료 F
    observed_at: datetime | None = None
    source: str = ""
    verified: bool = False                   # 채널 정책·연동이 확인되었는가


@dataclass(frozen=True)
class OptionCostInput:
    """옵션 1개의 원가 입력. 수량은 1 이상의 정수(세트 수량)."""
    unit_price: Decimal
    currency: str = "CNY"
    quantity: int = 1
    weight_g: Decimal | None = None
    dims_cm: tuple[Decimal, Decimal, Decimal] | None = None
    china_shipping_krw: Decimal | None = ZERO
    handling_krw: Decimal | None = ZERO             # 검수/포장
    seller_customs_krw: Decimal | None = ZERO       # 판매자 부담 통관비·세금
    domestic_shipping_krw: Decimal | None = ZERO
    payment_fee_rate: Decimal | None = ZERO         # 환전/결제 비용 (상품대금 기준)
    reserve_rate: Decimal | None = ZERO             # 반품/불량 충당금 (위 합계 기준)


@dataclass(frozen=True)
class SaleTerms:
    free_shipping: bool = True
    customer_shipping_krw: Decimal = ZERO    # 별도 배송비 S
    seller_discount_rate: Decimal = ZERO     # 판매자 부담 할인 (표시가에서 차감)
    target_margin: Decimal = Decimal("0.20")
    rounding_unit: int = 100


MAX_AGE = {"fx": timedelta(hours=24), "shipping": timedelta(days=30), "channel": timedelta(days=30)}


@dataclass
class PriceQuote:
    channel: str
    status: str                              # "ok" | "incomplete" | "below_target"
    publishable: bool
    blockers: list[str] = field(default_factory=list)
    list_price: int | None = None            # 표시 판매가(할인 전 상품가)
    paid_product_krw: int | None = None      # 할인 후 상품 결제액
    customer_shipping_krw: int = 0
    total_paid_krw: int | None = None        # 고객 총 결제액
    total_cost_krw: int | None = None
    cost_breakdown: dict[str, int] = field(default_factory=dict)
    commission_krw: int | None = None
    shipping_fee_krw: int | None = None
    fixed_fee_krw: int | None = None
    profit_krw: int | None = None
    margin: Decimal | None = None
    scenarios: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["margin"] = None if self.margin is None else str(self.margin)
        return d


def _check_age(label: str, observed: datetime | None, kind: str, now: datetime, out: list[str]) -> None:
    obs = _aware(observed)
    if obs is None:
        out.append(f"{label}: 확인 시각 없음")
    elif now - obs > MAX_AGE[kind]:
        out.append(f"{label}: 만료됨 (확인 {obs.isoformat()})")
    elif obs > now + timedelta(minutes=5):
        out.append(f"{label}: 확인 시각이 미래입니다")


def landed_cost(opt: OptionCostInput, fx: FxRate, ship: ShippingRateCard, now: datetime
                ) -> tuple[dict[str, int] | None, list[str]]:
    """원가 구성을 계산. 입력이 없거나 만료되면 (None, blockers) 반환 — 0으로 대체하지 않는다."""
    _nonneg(opt.unit_price, "unit_price")
    if opt.currency not in SUPPORTED_SOURCE_CURRENCIES:
        raise ValidationError(f"지원하지 않는 통화: {opt.currency!r}")
    if isinstance(opt.quantity, bool) or not isinstance(opt.quantity, int) or not 1 <= opt.quantity <= MAX_QUANTITY:
        raise ValidationError(f"비정상 수량: {opt.quantity!r}")
    if fx.currency != opt.currency:
        raise ValidationError(f"환율 통화({fx.currency})와 상품 통화({opt.currency})가 다릅니다")
    blockers: list[str] = []
    for n in ("china_shipping_krw", "handling_krw", "seller_customs_krw", "domestic_shipping_krw",
              "payment_fee_rate", "reserve_rate"):
        value = getattr(opt, n)
        if value is None:
            blockers.append(f"{n}: 비용 미확인 (0원도 명시 필요)")
        elif n.endswith("rate"):
            _rate(value, n)
        else:
            _nonneg(value, n)
    if fx.krw_per_unit is None:
        blockers.append("환율 없음")
    else:
        if _nonneg(fx.krw_per_unit, "fx") <= 0:
            raise ValidationError("환율은 0보다 커야 합니다")
        _check_age("환율", fx.observed_at, "fx", now, blockers)
    if ship.rate_per_kg is None:
        blockers.append("국제배송 요율 없음")
    else:
        _nonneg(ship.rate_per_kg, "rate_per_kg")
        _check_age("국제배송 요율", ship.observed_at, "shipping", now, blockers)
    if opt.weight_g is None:
        blockers.append("무게 없음")
    elif _nonneg(opt.weight_g, "weight_g") <= 0:
        raise ValidationError("무게는 0보다 커야 합니다")
    if blockers:
        return None, blockers

    actual = opt.weight_g * opt.quantity
    volumetric = ZERO
    if opt.dims_cm:
        l, w, h = (_nonneg(x, "dims_cm") for x in opt.dims_cm)
        if ship.volumetric_divisor <= 0:
            raise ValidationError("부피중량 나눗수는 0보다 커야 합니다")
        volumetric = l * w * h * opt.quantity / ship.volumetric_divisor * 1000  # g
    billable = max(actual, volumetric, ship.min_billable_g)
    step = ship.billing_step_g if ship.billing_step_g > 0 else ONE
    billable = (billable / step).to_integral_value(rounding=ROUND_CEILING) * step

    product = won_ceil(opt.unit_price * opt.quantity * fx.krw_per_unit)
    payment_fee = won_ceil(product * opt.payment_fee_rate)
    intl = won_ceil(billable / 1000 * ship.rate_per_kg)
    parts = {
        "product": product, "payment_fee": payment_fee,
        "china_shipping": won_ceil(opt.china_shipping_krw), "handling": won_ceil(opt.handling_krw),
        "intl_shipping": intl, "customs": won_ceil(opt.seller_customs_krw),
        "domestic_shipping": won_ceil(opt.domestic_shipping_krw),
    }
    reserve = won_ceil(sum(parts.values()) * opt.reserve_rate)
    parts["reserve"] = reserve
    return {k: int(v) for k, v in parts.items()}, []


def _margin(paid_total: Decimal, cost: Decimal, commission: Decimal, ship_fee: Decimal, fixed: Decimal
            ) -> tuple[Decimal, Decimal]:
    profit = paid_total - cost - commission - ship_fee - fixed
    return profit, profit / paid_total


def quote_price(opt: OptionCostInput, fx: FxRate, ship: ShippingRateCard, channel: ChannelTerms,
                sale: SaleTerms, now: datetime) -> PriceQuote:
    """옵션×채널 1건의 판매가를 계산한다. 입력 부족/만료 시 publishable=False, 가격 없음."""
    now = _aware(now)
    m = _rate(sale.target_margin, "target_margin")
    disc = _rate(sale.seller_discount_rate, "seller_discount_rate")
    unit = sale.rounding_unit
    if isinstance(unit, bool) or not isinstance(unit, int) or unit < 1:
        raise ValidationError(f"rounding_unit 오류: {unit!r}")
    s_cust = ZERO if sale.free_shipping else _nonneg(sale.customer_shipping_krw, "customer_shipping_krw")
    fixed = _nonneg(channel.fixed_fee, "fixed_fee")

    parts, blockers = landed_cost(opt, fx, ship, now)
    blockers = list(blockers)
    if channel.commission_rate is None:
        blockers.append("채널 수수료율 없음")
    if not sale.free_shipping and channel.shipping_fee_rate is None:
        blockers.append("채널 배송비 수수료율 없음")
    if channel.commission_rate is not None:
        _check_age("채널 수수료", channel.observed_at, "channel", now, blockers)
    if blockers or parts is None:
        return PriceQuote(channel.channel, "incomplete", False, blockers)

    rp = _rate(channel.commission_rate, "commission_rate")
    rs = _rate(channel.shipping_fee_rate if channel.shipping_fee_rate is not None else ZERO, "shipping_fee_rate")
    C = Decimal(sum(parts.values()))
    if ONE - rp - m <= 0:
        raise ValidationError(f"분모가 0 이하입니다 (1 - 수수료율 {rp} - 목표마진 {m})")
    if not sale.free_shipping and ONE - rs - m <= 0:
        raise ValidationError(f"배송비 분모가 0 이하입니다 (1 - {rs} - {m})")

    # 할인 후 결제액 기준의 이론 상품 결제액 X
    if sale.free_shipping:
        x_paid = (C + fixed) / (ONE - rp - m)
    else:
        x_paid = (C + fixed - (ONE - rs - m) * s_cust) / (ONE - rp - m)
    if x_paid <= 0:
        raise ValidationError("계산된 판매가가 0 이하입니다 (입력 오류)")
    list_price = (x_paid / (ONE - disc) / unit).to_integral_value(rounding=ROUND_CEILING) * unit

    def evaluate(lp: Decimal):
        paid_p = won_half_up(lp * (ONE - disc))        # 할인은 이미 결제액에 반영: 다시 차감하지 않는다
        comm = won_half_up(paid_p * rp)
        sfee = won_half_up(s_cust * rs) if not sale.free_shipping else ZERO
        total = paid_p + s_cust
        profit, mg = _margin(total, C, comm, sfee, fixed)
        return paid_p, comm, sfee, total, profit, mg

    for _ in range(200):  # 원단위 반올림 오차로 미달이면 한 단위씩 올려 재검산
        paid_p, comm, sfee, total, profit, mg = evaluate(list_price)
        if mg >= m:
            break
        list_price += unit
    else:
        raise ValidationError("목표 마진을 만족하는 가격을 찾지 못했습니다")

    scenarios = {}
    for pct in (5, 10):  # 원가 상승 시나리오: 판매가 고정, 원가만 상승
        c2 = C * (ONE + Decimal(pct) / 100)
        scenarios[f"cost+{pct}%"] = str(_margin(total, c2, comm, sfee, fixed)[1].quantize(Decimal("0.0001")))
    return PriceQuote(
        channel.channel, "ok", True, [], int(list_price), int(paid_p), int(s_cust), int(total), int(C),
        parts, int(comm), int(sfee), int(fixed), int(profit), mg, scenarios)


def evaluate_existing_price(opt: OptionCostInput, fx: FxRate, ship: ShippingRateCard, channel: ChannelTerms,
                            sale: SaleTerms, list_price: int, now: datetime) -> PriceQuote:
    """이미 정해진 표시가(예: 쿠폰·할인 적용 후)의 실제 마진을 평가한다. 미달이면 below_target."""
    now = _aware(now)
    parts, blockers = landed_cost(opt, fx, ship, now)
    if channel.commission_rate is None:
        blockers.append("채널 수수료율 없음")
    if not sale.free_shipping and channel.shipping_fee_rate is None:
        blockers.append("채널 배송비 수수료율 없음")
    _check_age("채널 수수료", channel.observed_at, "channel", now, blockers)
    if parts is None or blockers:
        return PriceQuote(channel.channel, "incomplete", False, blockers)
    if list_price <= 0:
        raise ValidationError("판매가는 0보다 커야 합니다")
    rp = _rate(channel.commission_rate, "commission_rate")
    rs = _rate(channel.shipping_fee_rate or ZERO, "shipping_fee_rate")
    disc = _rate(sale.seller_discount_rate, "seller_discount_rate")
    s_cust = ZERO if sale.free_shipping else _nonneg(sale.customer_shipping_krw, "customer_shipping_krw")
    C = Decimal(sum(parts.values()))
    paid_p = won_half_up(Decimal(list_price) * (ONE - disc))
    comm = won_half_up(paid_p * rp)
    sfee = ZERO if sale.free_shipping else won_half_up(s_cust * rs)
    total = paid_p + s_cust
    fixed = _nonneg(channel.fixed_fee, "fixed_fee")
    if total <= 0:
        raise ValidationError("고객 결제액은 0보다 커야 합니다")
    profit, mg = _margin(total, C, comm, sfee, fixed)
    ok = mg >= _rate(sale.target_margin, "target_margin")
    return PriceQuote(channel.channel, "ok" if ok else "below_target", ok,
                      [] if ok else [f"마진 미달 {mg.quantize(Decimal('0.0001'))}"], int(list_price), int(paid_p),
                      int(s_cust), int(total), int(C), parts, int(comm), int(sfee), int(channel.fixed_fee),
                      int(profit), mg)
