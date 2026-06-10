# Pearlshore Technologies Website

A responsive Flask and SQLite business website with public marketing pages,
contact inquiry storage, newsletter subscriptions, and a secure admin dashboard.

## Run locally

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Default admin login

- URL: `http://127.0.0.1:5000/admin/login`
- Email: `admin@pearlshore.com`
- Password: `ChangeMe123!`

Set `ADMIN_EMAIL`, `ADMIN_PASSWORD`, and `SECRET_KEY` before the first
production run. Delete `instance/pearlshore.db` only when intentionally
resetting all local data.

## Gmail email delivery

Contact messages are always stored in SQLite. To email them to
`kamalasruthi03@gmail.com`:

1. Enable 2-Step Verification on the sending Google account.
2. Create a Google App Password for Mail.
3. Copy `.env.example` to `.env`.
4. Replace `SMTP_PASSWORD` with the 16-character app password.
5. Restart the Flask server.

Do not use the normal Gmail password and do not commit `.env`.
