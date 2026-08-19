import unittest

from cat_sync_final import calculate_sale_price, identify_retailer, is_suspicious_price
from mart_scrapers import SyncStatus, parse_emart_html, parse_homeplus_html


class RetailerDetectionTests(unittest.TestCase):
    def test_detects_retailers_from_url_or_source(self):
        self.assertEqual(identify_retailer({"reference": "https://front.homeplus.co.kr/item/1"}), "homeplus")
        self.assertEqual(identify_retailer({"reference": "https://www.ssg.com/item/1"}), "emart")
        self.assertEqual(identify_retailer({"purchaseSource": "이마트"}), "emart")
        self.assertIsNone(identify_retailer({"purchaseSource": "코스트코"}))

    def test_sale_price_formula_is_preserved(self):
        self.assertEqual(calculate_sale_price(10_000), 10_790)

    def test_large_price_change_is_reviewed(self):
        self.assertTrue(is_suspicious_price(10_000, 14_000, 0.30))
        self.assertFalse(is_suspicious_price(10_000, 12_000, 0.30))
        self.assertFalse(is_suspicious_price(None, 12_000, 0.30))


class ParserTests(unittest.TestCase):
    def test_parses_emart_price(self):
        result = parse_emart_html('<em class="ssg_price" data-prc="20980">20,980</em>')
        self.assertEqual(result.status, SyncStatus.AVAILABLE)
        self.assertEqual(result.buying_price, 20_980)

    def test_parses_homeplus_discount_prices(self):
        result = parse_homeplus_html(
            '<span class="priceType">8,900원</span><span class="priceItem dc">10,000원</span>'
        )
        self.assertEqual(result.status, SyncStatus.AVAILABLE)
        self.assertEqual(result.buying_price, 8_900)
        self.assertEqual(result.original_price, 10_000)

    def test_sold_out_requires_purchase_area(self):
        sold_out = parse_emart_html(
            '<div class="cdtl_btn_wrap"><button>일시품절</button></div><em class="ssg_price">9,900</em>'
        )
        unrelated_text = parse_emart_html(
            '<p>품절 상품 관련 안내</p><button>장바구니</button><em class="ssg_price">9,900</em>'
        )
        self.assertEqual(sold_out.status, SyncStatus.SOLD_OUT)
        self.assertEqual(unrelated_text.status, SyncStatus.AVAILABLE)

    def test_access_block_is_not_treated_as_sold_out(self):
        result = parse_homeplus_html('<html><title>Access Denied</title></html>')
        self.assertEqual(result.status, SyncStatus.ERROR)


if __name__ == "__main__":
    unittest.main()
