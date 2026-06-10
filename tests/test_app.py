import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as pearlshore


class PearlshoreAppTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        pearlshore.app.config.update(
            TESTING=True,
            DATABASE=str(Path(self.temp_dir.name) / "test.db"),
            SECRET_KEY="test-secret",
        )
        with pearlshore.app.app_context():
            pearlshore.init_db()
        self.client = pearlshore.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf(self):
        with self.client.session_transaction() as session:
            session["_csrf_token"] = "test-token"
        return "test-token"

    def login(self):
        return self.client.post(
            "/admin/login",
            data={
                "_csrf_token": self.csrf(),
                "email": "admin@pearlshore.com",
                "password": "ChangeMe123!",
            },
            follow_redirects=True,
        )

    def test_public_pages_render(self):
        for path in ["/", "/about", "/services", "/contact"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(b"PearlShore", response.data)

    def test_contact_submission_is_stored(self):
        response = self.client.post(
            "/contact",
            data={
                "_csrf_token": self.csrf(),
                "name": "Test Client",
                "email": "client@example.com",
                "phone": "12345",
                "service": "Product Development & Engineering",
                "message": "We need a new digital product.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Your message has been received", response.data)
        with pearlshore.app.app_context():
            count = pearlshore.get_db().execute(
                "SELECT COUNT(*) FROM inquiries"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    @patch("app.smtplib.SMTP_SSL")
    @patch.dict(
        "os.environ",
        {
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "465",
            "SMTP_USE_SSL": "true",
            "SMTP_USER": "kamalasruthi03@gmail.com",
            "SMTP_PASSWORD": "app-password",
            "CONTACT_EMAIL": "kamalasruthi03@gmail.com",
        },
    )
    def test_contact_email_delivery_is_recorded(self, smtp_ssl):
        response = self.client.post(
            "/contact",
            data={
                "_csrf_token": self.csrf(),
                "name": "Mail Test",
                "email": "client@example.com",
                "phone": "",
                "service": "",
                "message": "Please contact me.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        smtp_ssl.return_value.__enter__.return_value.send_message.assert_called_once()
        with pearlshore.app.app_context():
            status = pearlshore.get_db().execute(
                "SELECT email_status FROM inquiries ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        self.assertEqual(status, "sent")

    def test_admin_login_and_service_crud(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Good to see you", response.data)

        response = self.client.post(
            "/admin/services/new",
            data={
                "_csrf_token": self.csrf(),
                "title": "Cloud Enablement",
                "icon": "product",
                "description": "Secure cloud architecture and delivery.",
                "benefits": "Architecture, Migration",
                "technologies": "AWS, Docker",
                "display_order": "4",
                "is_active": "on",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Cloud Enablement", response.data)

    def test_admin_is_protected(self):
        response = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
