"""Independent specification regressions; run from the AUTO-NAVER checkout."""
import csv
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from app.purchasing.importer import CSV_COLUMNS, import_csv, import_json
from app.purchasing.pricing import ChannelTerms, FxRate, OptionCostInput, SaleTerms, ShippingRateCard, evaluate_existing_price, quote_price
from app.purchasing.workflow import option_input
N = datetime(2026, 11, 4, tzinfo=timezone.utc)

def product(pid='P1'):
    return {'source_product_id':pid,'title_src':'box','options':[{'source_option_id':'A','name':'white','unit_price':'100','weight_g':'300'}]}

class IndependentPricingRegression(unittest.TestCase):
    def test_unknown_shipping_and_costs_cannot_be_confirmed(self):
        row=import_json(json.dumps({'schema_version':1,'products':[product()]})).accepted[0]
        q=quote_price(option_input(row['options'][0]),FxRate('CNY',D(190),N),ShippingRateCard(D(9000),N),ChannelTerms('smartstore',D('.06'),D('.03'),observed_at=N),SaleTerms(),N)
        self.assertFalse(q.publishable,'Unspecified domestic shipping, payment fee, reserve, and dimensions must not silently become confirmed zero/actual-only values.')

    def test_csv_conflicting_product_compliance_does_not_disappear(self):
        out=io.StringIO(); w=csv.DictWriter(out,fieldnames=CSV_COLUMNS); w.writeheader()
        for oid,allowed,flags in [('A','true',''),('B','false','battery')]:
            row=dict.fromkeys(CSV_COLUMNS,''); row.update(schema_version='1',source_product_id='P1',title_src='box',source_option_id=oid,option_name=oid,unit_price='100',sale_allowed_confirmed=allowed,restricted_flags=flags);w.writerow(row)
        report=import_csv(out.getvalue())
        self.assertEqual(len(report.accepted),0,'Conflicting product metadata should reject the group, not keep the first row as sale-allowed.')

    def test_malformed_flag_is_a_row_rejection_not_a_batch_crash(self):
        bad=product(); bad['compliance']={'restricted_flags':[{}]}
        report=import_json(json.dumps({'schema_version':1,'products':[bad,product('P2')]}))
        self.assertEqual(report.summary,{'accepted':1,'rejected':1})

    def test_existing_price_rechecks_missing_and_stale_channel_fees(self):
        q=evaluate_existing_price(OptionCostInput(D(100),weight_g=D(300)),FxRate('CNY',D(190),N),ShippingRateCard(D(9000),N),ChannelTerms('smartstore',D('.06'),None,observed_at=N-timedelta(days=60)),SaleTerms(free_shipping=False,customer_shipping_krw=D(3000)),50000,N)
        self.assertFalse(q.publishable)
        self.assertEqual(q.status,'incomplete')

if __name__=='__main__': unittest.main(verbosity=2)
