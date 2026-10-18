# family-messenger

Guardian's iMessage relay, built on [Photon Spectrum](https://photon.codes/docs/spectrum-ts). The backend
never talks to Photon directly; it posts each family alert here.

- `POST /send {to, text}` sends `text` as an iMessage to `to` (called by `backend/app/notify.py` when
  `PHOTON_SIDECAR_URL` is set).
- Replies from the family (`BLOCK`, `SAFE`) are forwarded to `{BACKEND_URL}/webhooks/photon` as `{from, text}`.
- `GET /health` returns `{ok: true}`.

## Environment (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `PROJECT_ID`, `PROJECT_SECRET` | | Spectrum Cloud project (Photon dashboard → project settings) |
| `BACKEND_URL` | `http://localhost:8000` | Where replies are forwarded |
| `PHOTON_SIDECAR_PORT` | `8787` | Port for `/send` |
| `PHOTON_SIDECAR_SECRET` | | Optional bearer token the backend must send |

On shared-pool Photon plans, every recipient must be added as a project user in the dashboard first.

## Run

```sh
npm install
npm start
```

In production it runs inside the same container as the backend (see the root `Dockerfile` and
`backend/deploy/start.sh`).
