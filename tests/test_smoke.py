from app.main_v31 import app
from app.services import calculate_sale_price


def test_app_imports():
    assert app.title.startswith('STORMPC AUTO COMMERCE')


def test_price_calculation():
    price = calculate_sale_price(100000)
    assert price >= 108000
    assert price % 1000 == 0
