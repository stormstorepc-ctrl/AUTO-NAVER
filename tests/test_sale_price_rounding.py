from app.services import calculate_sale_price


def test_exact_margin_is_not_rounded_up_by_float_error():
    # 225000 * 1.08 == 243000 정확히 -> 1000원 단위 올림 결과 243000
    assert calculate_sale_price(225000) == 243000


def test_regular_rounding_and_zero():
    assert calculate_sale_price(0) == 0
    assert calculate_sale_price(10000) == 11000
    assert calculate_sale_price(10001) == 11000
