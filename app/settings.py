from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./stormpc.db'
    admin_username: str = 'ADMIN'
    admin_password: str = 'ADMIN'
    secret_key: str = 'change-me'
    macromart_id: str = ''
    macromart_password: str = ''
    macromart_headless: bool = False
    macromart_base_url: str = 'https://macromart.co.kr'
    macromart_start_url: str = 'https://macromart.co.kr/index.html'
    default_margin_rate: float = 0.08
    price_round_unit: int = 1000
    max_auto_price_change_rate: float = 0.15
    default_safety_stock: int = 0
    default_min_sale_price: int = 0
    naver_commerce_client_id: str = ''
    naver_commerce_client_secret: str = ''
    naver_commerce_account_id: str = ''
    naver_client_id: str = ''
    naver_client_secret: str = ''
    naver_redirect_uri: str = 'http://127.0.0.1:8000/naver/callback'
    naver_cafe_club_id: str = ''
    naver_cafe_menu_id: str = ''
    naver_cafe_access_token: str = ''
    auto_approval: bool = False

settings = Settings()
