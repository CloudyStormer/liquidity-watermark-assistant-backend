# Watermark Assistant Backend

Backend services for the `aaa` frontend module.

## Features

- Mini-program user identity by `openid`
- Image/video upload jobs for authorized watermark cleanup
- User ratings
- User feedback
- Queryable operation logs for each user
- Local SQLite persistence and local file storage

The media cleanup service is intended for user-owned or authorized materials. It does not parse platform links or bypass platform watermarks.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

For video processing, install FFmpeg and make sure `ffmpeg` is on `PATH`, or set `FFMPEG_PATH` in `.env`.

## Run

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs`.

## Key APIs

- `POST /api/users/login`
- `GET /api/users/{openid}/profile`
- `POST /api/media/jobs/upload`
- `GET /api/media/jobs/{job_id}`
- `GET /api/media/jobs/{job_id}/download`
- `GET /api/users/{openid}/media/jobs`
- `POST /api/ratings`
- `GET /api/users/{openid}/ratings`
- `POST /api/feedback`
- `GET /api/users/{openid}/feedback`
- `GET /api/users/{openid}/logs`

## Upload Example

```powershell
curl -X POST http://127.0.0.1:8000/api/media/jobs/upload `
  -F "openid=o_demo_123" `
  -F "rights_confirmed=true" `
  -F "method=blur" `
  -F "regions_json=[{\"x\":0,\"y\":0,\"width\":160,\"height\":80,\"blur_radius\":24}]" `
  -F "file=@D:\demo.png"
```
