# FaceForm backend

FastAPI monolith for FaceForm. It provides account and Firebase authentication, fictional-face generation, image galleries and albums, a credit ledger, M-Pesa (STK, Paybill, Till and Daraja QR), and Stripe Checkout.

## Run locally

1. Install Python 3.11 or newer and PostgreSQL.
2. From this directory, create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

3. Set `DATABASE_URL`, a strong `JWT_SECRET`, and credentials for the providers you intend to use in `.env`.
4. Start the API:

   ```powershell
   uvicorn app.main:app --reload
   ```

The server renders the responsive Jinja frontend at `/`, `/product`, `/login`, `/register`, `/dashboard`, `/gallery`, and `/billing`. The JSON API is rooted at `/api/v1`; interactive OpenAPI documentation is available at `/docs`.

## Provider setup

- **Face generation:** `IMAGE_GENERATION_API_URL` must be an OpenAI-compatible image-generation endpoint returning hosted URLs in `data[].url`. Set its API key and, optionally, model name. Generation returns a clear `503` until configured; there is no fake-image fallback.
- **Google login:** Set `FIREBASE_CREDENTIALS` to a Firebase Admin service-account JSON file and set the four `FIREBASE_WEB_*` values for the Firebase web app. The frontend sends its Firebase ID token to `POST /api/v1/auth/firebase`.
- **M-Pesa:** Add Daraja credentials, shortcode, passkey, and a public `MPESA_CALLBACK_URL` ending in `/api/v1/billing/mpesa/callback`. Configure the Daraja callback URL to the same endpoint. Paybill/Till receipts are confirmed by a trusted integration calling `/api/v1/billing/manual/callback` with `X-Payment-Webhook-Secret`.
- **Cards:** Configure a Stripe secret key, webhook secret, success URL, and cancel URL. Register `/api/v1/billing/stripe/webhook` for `checkout.session.completed`.

M-Pesa callbacks and Stripe webhooks are idempotent: a payment grants credits only once and only after provider confirmation. Manual Paybill/Till/QR payments remain pending until the trusted manual callback confirms the receipt and exact amount.

## Main API routes

| Area | Routes |
|---|---|
| Auth | `POST /auth/register`, `/auth/login`, `/auth/firebase`; `GET /auth/me` |
| Generate | `POST /generations`; `GET/DELETE /generations/{id}`; `PATCH /generations/{id}` and `POST /generations/{id}/regenerate` |
| Gallery | `GET /gallery`; `PATCH/DELETE /images/{id}`; `GET /images/{id}/download` |
| Albums | `GET/POST /albums`; `PATCH/DELETE /albums/{id}`; attach/remove image routes under `/albums/{id}/images/{image_id}` |
| Billing | `GET /billing/packs`; `POST /billing/payments`; `GET /billing/payments`; provider callbacks |
| Dashboard | `GET /dashboard` |

Guests can generate one image and receive a signed guest token. Send that token as `guest_token` when registering or signing in to claim the generation and make its download available to the account. Authenticated generation costs `CREDITS_PER_IMAGE` credits per requested image; failed provider requests are refunded.
