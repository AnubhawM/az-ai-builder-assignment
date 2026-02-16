# AIXplore Capability Exchange

## Overview
AIXplore Capability Exchange is a collaborative workflow platform for AI-assisted research and presentation generation.

## Prerequisites
- Python 3.12+
- Conda (recommended)
- Node.js + npm
- OpenClaw installed locally
- API keys configured in backend/frontend `.env` files

## 1. Clone The Repository
```bash
git clone https://github.com/AnubhawM/az-ai-builder-assignment.git
cd az-ai-builder-assignment
```

## 2. Backend Setup
From the project root:

```bash
cd backend
conda create --name <env-name> python=3.12.1 -y
conda activate <env-name>
pip install -r requirements.txt
```

Configure backend environment variables:

```bash
cp .env.template .env
```

Then fill in all required secrets in `backend/.env`.

Run the backend:

```bash
python app.py
```

## 3. Frontend Setup
From the backend directory:

```bash
cd ../frontend
npm install
```

Configure frontend environment variables:

```bash
cp .env.template .env
```

Then fill in all required secrets in `frontend/.env`.

Run the frontend:

```bash
npm run dev
```

## 4. OpenClaw Setup
Install and onboard OpenClaw using the official repository:

https://github.com/openclaw/openclaw

During onboarding:
- Select a supported model provider and configure API keys.
- Enable Brave web search and provide a Brave API key (Between the free plans, select Free AI plan - it allows agentic web search).

If you need to change OpenClaw configuration later:

```bash
openclaw configure
```

Start OpenClaw gateway:

```bash
openclaw gateway run
```

Open the dashboard:

http://localhost:18789/overview

## 5. Run The Full App
Once backend, frontend, and OpenClaw are running, the platform is ready to use.

## Notes
- `.env` files are ignored by git and should never be committed.
- If any service fails to start, verify `.env` values and API keys first.
