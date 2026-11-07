"""서버에서 렌더링하는 구매대행 시연 화면. 외부 HTML/스크립트는 실행하지 않는다."""
from html import escape as E

from .assist import translation_request

COST_LABELS = {
    "china_shipping_krw": "중국 내 배송비(원)", "handling_krw": "검수·포장비(원)",
    "seller_customs_krw": "판매자 부담 통관비(원)", "domestic_shipping_krw": "국내 배송비(원)",
    "payment_fee_rate": "환전·결제비율(%)", "reserve_rate": "반품 충당금 비율(%)",
}


def input_field(name, label, value="", required=True):
    return (f"<label>{E(label)} <input name='{E(str(name), quote=True)}' "
            f"value='{E(str(value), quote=True)}' {'required' if required else ''}></label>")


def channel_nav(channel):
    return "<nav>" + " · ".join(
        f"<a href='/?channel={key}' {'aria-current=page' if key == channel else ''}>{label}</a>"
        for key, label in (("smartstore", "스마트스토어"), ("danggeun", "당근"), ("bunjang", "번개장터"))) + "</nav>"


def import_form():
    return """<h1>상품 가져오기</h1>
<p class=notice>실제 타오바오 상품은 <a href='/import/url'>주소로 상품 추가</a>를 이용하세요.</p>
<p>JSON 또는 CSV 파일을 선택하세요.</p>
<p>처음 사용한다면 <a href='/sample.json' download>가상 상품 샘플 다운로드</a> 후 아래에서 선택하세요.
샘플의 상품·이미지·비용은 모두 시연용입니다.</p>
<form method=post action='/import' enctype='multipart/form-data'>
<label>형식 <select name=format><option value=json>JSON</option><option value=csv>CSV</option></select></label>
<label>파일(최대 2MB) <input type=file name=file accept='.json,.csv'></label>
<label>또는 내용을 붙여넣기 <textarea name=raw rows=8></textarea></label>
<button>상품 가져오기</button></form>"""


def url_import_form():
    return """<h1>주소로 상품 추가</h1>
<section><h2>1. 상품 페이지 내용 복사</h2>
<ol><li>Chrome에서 타오바오 상품 페이지를 엽니다.</li>
<li>주소창의 주소를 복사해서 아래 <b>상품 주소</b>에 붙여넣습니다.</li>
<li>상품 페이지 아무 곳이나 클릭한 뒤 <b>Ctrl+A</b>, <b>Ctrl+C</b>를 누르고 아래 <b>페이지 내용</b>에 붙여넣습니다.</li></ol>
<p>이 프로그램은 타오바오에 직접 접속하지 않습니다. 화면에 보이는 글만 사용합니다.</p>
<form method=post action='/import/url'>
<label>상품 주소 <input name=url required placeholder='https://item.taobao.com/item.htm?id=...' style='width:100%'></label>
<label>페이지 내용 <textarea name=page_text rows=10 required></textarea></label>
<button>다음: Claude 요청 문구 만들기</button></form></section>"""


def url_import_reply_form(url, request_text):
    return (f"<h1>주소로 상품 추가</h1><section><h2>2. Claude에게 정보 정리 맡기기</h2>"
            "<ol><li>아래 요청 문구 칸을 클릭하고 <b>Ctrl+A</b>, <b>Ctrl+C</b>로 복사합니다.</li>"
            "<li>Claude 채팅(claude.ai)에 붙여넣고 보냅니다.</li>"
            "<li>Claude 답변을 복사해서 아래 <b>Claude 답변</b> 칸에 붙여넣습니다.</li></ol>"
            f"<label>요청 문구 <textarea rows=10 readonly>{E(request_text)}</textarea></label></section>"
            "<section><h2>3. 답변 붙여넣고 저장</h2>"
            f"<form method=post action='/import/url/save'><input type=hidden name=url value='{E(url, quote=True)}'>"
            "<label>Claude 답변 <textarea name=reply rows=10 required></textarea></label>"
            "<label>상품 이미지 주소 (한 줄에 하나. 타오바오에서 사진을 오른쪽 클릭 → '이미지 주소 복사') "
            "<textarea name=image_urls rows=4></textarea></label>"
            "<p>예상 배송 기간(일, 중국 출발부터 고객 도착까지). 비워두면 답변의 값을 씁니다.</p>"
            "<label>최소 <input name=delivery_min inputmode=numeric size=4></label>"
            "<label>최대 <input name=delivery_max inputmode=numeric size=4></label>"
            "<p>이미지와 배송 기간이 없어도 저장은 되지만, 승인 단계에서 막힙니다.</p>"
            "<label><input type=checkbox name=sale_allowed value=yes> 한국에서 판매해도 되는 상품인지 확인했습니다 "
            "(체크하지 않으면 저장은 되지만 승인 단계에서 막힙니다)</label>"
            "<button>상품 저장</button></form></section>")


def translation_assist(p, request_text, hidden):
    return (f"<section><h2>Claude로 번역하기 (무료)</h2>"
            "<ol><li>아래 요청 문구 칸을 클릭하고 <b>Ctrl+A</b>, <b>Ctrl+C</b>로 복사합니다.</li>"
            "<li>Claude 채팅(claude.ai)에 붙여넣고 보냅니다.</li>"
            "<li>Claude 답변을 복사해서 아래 칸에 붙여넣고 저장합니다. 그다음 번역을 원문과 대조하고 검수 완료를 누르세요.</li></ol>"
            f"<label>요청 문구 <textarea rows=8 readonly>{E(request_text)}</textarea></label>"
            f"<form method=post action='/product/{p['id']}/translation/assist'>{hidden}"
            "<label>Claude 답변 <textarea name=reply rows=6 required></textarea></label>"
            "<button>답변으로 번역 초안 저장</button></form></section>")


def product_forms(p, tr, quotes, channel):
    pid = p["id"]
    hidden = (f"<input type=hidden name=channel value='{channel}'>"
              f"<input type=hidden name=product_version value='{p['version']}'>")
    translated = tr["option_names"] if tr else {}
    option_inputs = "".join(
        f"<p>원문 옵션 {E(o['source_option_id'])}: {E(o['name'])}</p>" +
        input_field(f"option_{i}", "한국어 옵션명", translated.get(o["source_option_id"], ""))
        for i, o in enumerate(p["options"]))
    translation = translation_assist(p, translation_request(p), hidden) + (
                   f"<section><h2>2. 한국어 상세페이지 입력</h2><p>번역문을 직접 입력하거나 위에서 Claude 답변으로 채운 뒤 원문과 대조하세요.</p>"
                   f"<form method=post action='/product/{pid}/translation'>{hidden}"
                   + input_field("title_ko", "한국어 상품명", tr["title_ko"] if tr else "") +
                   f"<label>한국어 상세 설명 <textarea name=description_ko rows=6 required>{E(tr['description_ko']) if tr else ''}</textarea></label>"
                   f"{option_inputs}<button>번역 초안 저장</button></form>")
    if tr:
        translation += (f"<form method=post action='/product/{pid}/translation/review'>{hidden}"
                        f"<input type=hidden name=translation_version value='{tr['version']}'>"
                        "<label><input type=checkbox name=confirmed value=yes required> 원문·수치·단위·옵션을 대조했습니다</label>"
                        "<button>이 번역 검수 완료</button></form>")
    translation += "</section>"

    # Only the supplied synthetic demo gets sample values. Real imports start blank.
    demo = p["source"] == "demo"
    latest = quotes[0]["inputs"] if quotes else {}
    fx = latest.get("fx", {}); shipping = latest.get("shipping", {}); terms = latest.get("channel", {})
    sale = latest.get("sale", {})
    def pct(value):
        from decimal import Decimal
        return "" if value is None else str(Decimal(str(value)) * 100)
    common = "".join((
        input_field("fx", "1 CNY당 원화 환율", fx.get("krw_per_unit", "190" if demo else "")),
        input_field("shipping_rate", "국제배송 1kg당 요율(원)", shipping.get("rate_per_kg", "9000" if demo else "")),
        input_field("min_billable_g", "최소 청구 중량(g)", shipping.get("min_billable_g", "500")),
        input_field("billing_step_g", "청구 중량 단위(g)", shipping.get("billing_step_g", "100")),
        input_field("volumetric_divisor", "부피중량 나눗수(cm³/kg)", shipping.get("volumetric_divisor", "5000")),
        input_field("commission_pct", "상품 판매 수수료(%)", pct(terms.get("commission_rate", "0.06" if demo else None))),
        input_field("shipping_fee_pct", "배송비 수수료(%)", pct(terms.get("shipping_fee_rate", "0.03" if demo else None))),
        input_field("fixed_fee", "건당 고정 수수료(원)", terms.get("fixed_fee", "0")),
        input_field("customer_shipping", "고객에게 별도로 받는 배송비(원, 무료배송은 0)", sale.get("customer_shipping_krw", "0")),
        input_field("discount_pct", "판매자 부담 할인(%)", pct(sale.get("seller_discount_rate", "0"))),
    ))
    options = ""
    for i, o in enumerate(p["options"]):
        options += f"<fieldset><legend>{E(o['source_option_id'])} · {E(o['name'])} · 원가 {E(o['unit_price'])} CNY</legend>"
        options += input_field(f"cost_{i}_weight_g", "실중량(g)", o.get("weight_g", ""))
        dims = o.get("dims_cm", ["", "", ""])
        for j, label in enumerate(("길이(cm)", "너비(cm)", "높이(cm)")):
            options += input_field(f"cost_{i}_dim_{j}", label, dims[j])
        for key, label in COST_LABELS.items():
            value = o.get(key, "")
            if key.endswith("rate") and value != "":
                value = pct(value)
            options += input_field(f"cost_{i}_{key}", label, value)
        options += "</fieldset>"
    pricing = (f"<section><h2>1. 배송비와 판매가 계산</h2>"
               f"<p>{'샘플 환율·수수료입니다. 실제 요율이 아닙니다.' if demo else '현재 확인한 환율·배송·수수료를 입력하세요.'} "
               "목표 마진은 총 결제액 대비 20%이며 고정비·소득세 차감 전입니다. 비용이 없으면 0을 명시하세요.</p>"
               f"<form method=post action='/product/{pid}/price'>{hidden}{common}{options}"
               "<label><input type=checkbox name=rates_confirmed value=yes required> 적용할 환율·배송·수수료를 확인했습니다(시연은 샘플값)</label>"
               "<button>전 옵션 가격 계산</button></form></section>")
    actions = (f"<section><h2>3. 승인 및 모의 등록</h2><form method=post action='/bulk'>"
               f"<input type=hidden name=ids value='{pid}'><input type=hidden name=channel value='{channel}'>"
               "<label>모의 계정 <input name=account value='mock:acct1' required></label>"
               "<button name=action value=approve>이 상품 승인</button> "
               "<button name=action value=publish>승인본 모의 등록</button></form>"
               f"<form method=post action='/product/{pid}/export'>{hidden}<button>검토용 상세페이지 ZIP 다운로드</button></form>"
               "<p>모의 계정에만 등록합니다. 스마트스토어·당근·번개장터 실제 판매글은 생성되지 않습니다.</p></section>")
    return pricing + translation + actions


def sample_document():
    return {"schema_version": 1, "products": [{
        "source": "demo", "source_product_id": "DEMO-BOX-001", "title_src": "演示用收纳盒", "category": "가상 수납용품",
        "description_src": "演示数据。尺寸 20 x 10 x 5 cm。非真实销售商品。",
        "supply_url": "https://example.invalid/demo/box", "images": ["https://example.invalid/demo/box.jpg"],
        "est_delivery_days": {"min": 7, "max": 14},
        "compliance": {"sale_allowed_confirmed": True, "restricted_flags": []},
        "options": [{"source_option_id": oid, "name": name, "unit_price": price, "currency": "CNY", "quantity": 1,
                     "weight_g": "300", "dims_cm": ["20", "10", "5"], "china_shipping_krw": "1000",
                     "handling_krw": "500", "seller_customs_krw": "0", "domestic_shipping_krw": "3000",
                     "payment_fee_rate": "0.02", "reserve_rate": "0.02"}
                    for oid, name, price in (("WHITE", "白色", "100"), ("BLACK", "黑色", "120"))]
    }]}
