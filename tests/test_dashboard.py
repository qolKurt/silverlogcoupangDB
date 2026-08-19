import unittest
from unittest.mock import Mock, patch

from app import app


class DashboardTests(unittest.TestCase):
    def test_emart_is_manual_and_homeplus_is_not_listed(self):
        client = Mock()
        client.get_catalogue.return_value = [
            {
                "_id": "emart-1",
                "name": "이마트 수동 상품",
                "reference": "https://emart.ssg.com/item/itemView.ssg?itemId=1",
                "purchaseSource": "이마트",
                "buyingPrice": 10_000,
                "price": 10_790,
                "originalPrice": 10_000,
                "active": True,
            },
            {
                "_id": "homeplus-1",
                "name": "홈플러스 자동 상품",
                "reference": "https://front.homeplus.co.kr/item/1",
                "purchaseSource": "홈플러스",
                "buyingPrice": 9_000,
                "price": 9_690,
                "originalPrice": 9_000,
                "active": True,
            },
        ]

        with patch("app.login_silverlog", return_value=client):
            response = app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("이마트 수동 상품", html)
        self.assertIn("이마트 🟡", html)
        self.assertNotIn("홈플러스 자동 상품", html)
        self.assertIn("홈플러스 가격/상태 자동 동기화", html)

    def test_dashboard_dispatch_explicitly_targets_homeplus(self):
        mocked_response = Mock(status_code=204)
        with (
            patch("app.GITHUB_TOKEN", "token"),
            patch("app.GITHUB_OWNER", "owner"),
            patch("app.GITHUB_REPO", "repo"),
            patch("app.requests.post", return_value=mocked_response) as post,
        ):
            response = app.test_client().post("/trigger-sync")

        self.assertEqual(response.status_code, 200)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["client_payload"]["retailer"], "homeplus")


if __name__ == "__main__":
    unittest.main()
