# Cloud Cost Intelligence — Backend API & Serverless Services

An enterprise AI-powered AWS Cost Intelligence backend built with **FastAPI**, **Amazon Bedrock (Claude 3 Haiku)**, **PostgreSQL (Amazon RDS)**, and **Mangum** for production deployment on **AWS Lambda** via **AWS SAM**.

---

## Technical Stack

- **Framework**: FastAPI 0.115.12
- **ASGI Serverless Adapter**: Mangum 0.19.0
- **Database & ORM**: PostgreSQL (Amazon RDS), SQLAlchemy 2.0, Alembic
- **AI & LLM Services**: Amazon Bedrock (`us.anthropic.claude-3-5-haiku-20241022-v1:0`)
- **Cloud Storage**: Amazon S3 (Cost Explorer CSV reports & Account Master ingestion)
- **Deployment**: AWS SAM (Serverless Application Model) & AWS Lambda

---

## Directory Structure

```text
cloud-cost-intelligence-backend/
├── app/
│   ├── api/                   # FastAPI route handlers (cost, qa, health, knowledge)
│   ├── db/                    # SQLAlchemy models, session & initialization scripts
│   ├── etl/                   # S3 CSV cost report parsing & PostgreSQL loader pipeline
│   ├── schemas/               # Pydantic DTOs & response schemas
│   ├── services/              # Bedrock LLM, Cost Query, Entity Resolver, Query Planner
│   ├── scheduler/             # Standalone & AWS Lambda event-driven sync handlers
│   ├── utils/                 # Structured JSON CloudWatch logging
│   ├── config.py              # Centralized environment settings
│   └── main.py                # FastAPI app & Mangum Lambda handler entrypoint
├── alembic/                   # Database migration environment & scripts
├── alembic.ini                # Alembic configuration
├── Dockerfile                 # Docker container definition
├── docker-compose.yml         # Local development orchestration
├── requirements.txt           # Python package dependencies
├── .env.example               # Environment variables template
└── README.md                  # Project documentation
```

---

## Local Setup & Development

### 1. Environment Configuration
Copy `.env.example` to `.env` and fill in your Amazon RDS PostgreSQL credentials and AWS access keys:

```bash
cp .env.example .env
```

### 2. Install Dependencies
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Initialize Database & Run Migrations
Execute out-of-band schema setup:
```bash
python -m app.db.init_db
```

### 4. Run API Server Locally
```bash
uvicorn app.main:app --reload --port 8000
```
API Documentation will be available at `http://localhost:8000/docs`.

### 5. Manual Cost ETL Synchronization
Run manual cost data sync from Amazon S3 into PostgreSQL:
```bash
python -m app.scheduler.sync_lambda
```

---

## AWS SAM Deployment (Serverless Production)

> [!NOTE]
> The application uses **Mangum** in `app/main.py` (`handler = Mangum(app)`).

### Deploy using AWS SAM CLI
```bash
sam build
sam deploy --guided
```

### Event-Driven Scheduling
Configure an **AWS EventBridge Rule / EventBridge Scheduler** to invoke `app.scheduler.sync_lambda.sync_handler` daily at 02:00 UTC to trigger automated S3 cost data ingestion into Amazon RDS PostgreSQL.

---

## Core API Endpoints

- `GET /health` — Service health status check
- `POST /ask` — Natural language cost analysis query via Bedrock Claude
- `GET /monthly-cost` — Aggregate monthly cost breakdown
- `GET /service-breakdown` — Service level cost distribution
- `POST /sync-cost-explorer` — Manual trigger for Cost Explorer sync
