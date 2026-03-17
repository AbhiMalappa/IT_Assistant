# IT Assistant — AI-Powered Incident Management Bot

A Slack bot that helps IT incident managers search past incidents, diagnose issues, analyze trends, and answer data questions — all via natural language.

Built by Abhiraj Malappa. Support: abhiraj7m@gmail.com

---

## What It Does

- **Semantic search** — "why does SAP fail?", "how are printer issues resolved?"
- **Exact lookup** — "what is the status of INC17089320?"
- **Aggregation** — "top 5 printer issues", "how many open critical incidents?"
- **Full system view** — "give me all SAP incidents"
- **Forecasting** — "how many incidents next month?", "predict SAP volume for next quarter"
- **Anomaly detection** — "are there any unusual spikes in incident volume?", "detect anomalies in network incidents"
- **Charts** — bar, line, horizontal bar, forecast, and anomaly charts posted inline in Slack with an interactive Plotly link
- **Conversation memory** — follow-up questions work across turns

---

## Prerequisites

- Python 3.11+
- [Anthropic API key](https://console.anthropic.com)
- [OpenAI API key](https://platform.openai.com) (for embeddings)
- [Pinecone account](https://www.pinecone.io)
- [Supabase account](https://supabase.com)
- [Slack workspace](https://slack.com) with admin access

---

## 1. Supabase Setup

1. Create a new Supabase project at [supabase.com](https://supabase.com).
2. Go to **SQL Editor** and run the full contents of `migrations/schema.sql`.
3. From **Project Settings → API**, copy:
   - `Project URL` → `SUPABASE_URL`
   - `service_role` key → `SUPABASE_SERVICE_KEY`
4. From **Project Settings → Database**, copy the connection string → `DATABASE_URL`.
   - Format: `postgresql://postgres:[password]@[host]:5432/postgres`

---

## 2. Pinecone Setup

1. Create an index at [pinecone.io](https://www.pinecone.io):
   - **Index name:** `it-assistant` (or your preferred name — set `PINECONE_INDEX_NAME`)
   - **Dimensions:** `3072` (for OpenAI `text-embedding-3-large`)
   - **Metric:** `cosine`
2. Copy your API key → `PINECONE_API_KEY`

> If switching to Voyage AI embeddings, set dimensions to `1024` and `EMBEDDING_PROVIDER=voyage`.

---

## 3. Slack App Setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.
2. Name it `IT Assistant`, select your workspace.

### Bot Token Scopes (OAuth & Permissions)
Add these under **Bot Token Scopes**:
- `app_mentions:read`
- `channels:history`
- `chat:write`
- `commands`
- `files:write`
- `im:history`
- `im:read`
- `im:write`

> `files:write` is required for posting charts inline in Slack. After adding it, reinstall the app to your workspace.

### Event Subscriptions
Enable **Event Subscriptions** and subscribe to bot events:
- `app_mention`
- `message.im`

### Socket Mode (for local dev)
- Enable **Socket Mode** under **Socket Mode**.
- Generate an App-Level Token with scope `connections:write` → `SLACK_APP_TOKEN`.

### Messages Tab (for DMs)
- Go to **App Home → Show Tabs** and enable the **Messages Tab**.
- Check "Allow users to send Slash commands and messages from the messages tab".

### Slash Command
- Go to **Slash Commands → Create New Command**:
  - Command: `/incident`
  - Description: `Search and manage IT incidents`
  - Usage hint: `search <query> | status <INC> | summary <INC> | help`

### Install to Workspace
- Go to **OAuth & Permissions → Install to Workspace**.
- Copy the **Bot User OAuth Token** → `SLACK_BOT_TOKEN`.
- Copy **Signing Secret** from **Basic Information** → `SLACK_SIGNING_SECRET`.

---

## 4. Local Setup

```bash
# Clone the repo
git clone <your-repo>
cd IT_Assistant

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and fill in all values

# Load incidents into Supabase (first time only)
python scripts/load_incidents.py

# Embed incidents into Pinecone (first time only)
python scripts/re_embed.py

# Run the bot
uvicorn main:app --reload
```

The bot connects to Slack via socket mode. You should see `⚡️ Bolt app is running!` in the logs.

---

## 5. Using the Bot in Slack

**@mention in a channel:**
```
@IT Assistant why does SAP keep failing?
@IT Assistant what is the status of INC17089320?
@IT Assistant top 5 printer issues this year
```

**Direct message:**
```
how many open critical incidents are there?
all incidents for the network team
summarize INC17089043
forecast incidents for next 3 months
are there any anomalies in monthly incident volume?
show me incidents by priority
```

**Slash commands:**
```
/incident search network outage
/incident status INC17089320
/incident summary INC17089043
/incident help
```

---

## 6. Deploy to Railway

1. Push your code to a GitHub repository.
2. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**.
3. Select your repository.
4. Go to **Variables** and add all environment variables from `.env.example`.
5. Set `APP_URL` to your Railway public URL (e.g. `https://itassistant-production-xxxx.up.railway.app`) — enables interactive Plotly chart links alongside inline PNG charts.
6. Railway will detect `railway.toml` and build from the `Dockerfile`.
7. Once deployed, Railway provides a public URL — you can use this for Slack's webhook URL if switching from socket mode.

> For production, switch from socket mode to HTTP mode by setting up Slack's **Event Subscriptions** URL to `https://your-railway-url/slack/events`.

---

## 7. Switching Embedding Providers

To switch from OpenAI to Voyage AI:

1. In `.env`, change `EMBEDDING_PROVIDER=openai` to `EMBEDDING_PROVIDER=voyage`.
2. Add your `VOYAGE_API_KEY`.
3. Update your Pinecone index dimensions to `1024`.
4. Re-embed all incidents:
   ```bash
   python scripts/re_embed.py
   ```

No other code changes needed.

---

## 8. Project Structure

```
IT_Assistant/
├── main.py                      # FastAPI entry point + Slack socket mode + /charts/{id} endpoint
├── bot/
│   ├── agent.py                 # Agentic loop — Claude picks tools at runtime (8 tools)
│   ├── tools.py                 # Tool implementations (search, SQL, lookup, forecast, anomaly, chart)
│   ├── slack_handler.py         # Slack Bolt event handling — posts text + uploads PNG charts
│   ├── conversation_manager.py  # Token-aware conversation memory (Supabase-backed)
│   ├── claude_client.py         # Anthropic client singleton
│   └── rag_pipeline.py          # Legacy RAG pipeline (superseded by agent + tools)
├── anomaly_detection/           # Standalone anomaly detection package (no project knowledge)
│   ├── analyser.py              # Pre-flight checks, seasonality/trend detection, method options
│   ├── threshold.py             # Auto Z-score threshold (3–9) based on noise level
│   ├── detector.py              # STL / MSTL / rolling Z-score + IQR capping
│   └── tool.py                  # analyse_for_anomalies() + run_anomaly_detection() wrappers
├── chart_png/                   # Standalone chart generation package (no project knowledge)
│   ├── generator.py             # Plotly figure builder (bar, line, forecast, anomaly)
│   ├── store.py                 # Saves PNG + HTML to /tmp/charts/
│   └── tool.py                  # plot_chart() wrapper
├── forecasting/                 # Standalone forecasting package
│   ├── forecaster.py            # Exponential Smoothing model selection by MSE
│   └── tool.py                  # forecast_incidents() wrapper
├── embeddings/
│   ├── base.py                  # Abstract BaseEmbedder
│   ├── openai_embedder.py       # OpenAI text-embedding-3-large
│   └── voyage_embedder.py       # Voyage AI (switchable)
├── vectorstore/
│   ├── base.py                  # Abstract BaseVectorStore
│   └── pinecone_store.py        # Pinecone implementation with namespace support
├── db/
│   ├── supabase_client.py       # Supabase client singleton
│   ├── incidents.py             # Incidents CRUD
│   └── conversation_messages.py # Conversation memory CRUD
├── scripts/
│   ├── load_incidents.py        # Load CSV incidents into Supabase
│   ├── re_embed.py              # Batch re-embed all incidents into Pinecone
│   └── sync_incidents.py        # Delta sync — CSV → Supabase → Pinecone (MD5 hash-based)
├── migrations/
│   └── schema.sql               # Full Supabase schema
├── docs/
│   ├── file_reference.md        # Plain English guide to every file
│   ├── conversation_memory.md   # Conversation memory architecture
│   └── tools/                   # Per-tool documentation
├── Inputs/
│   └── IT_Incidents_v1.csv      # Source incident data
├── .env.example                 # All required environment variables
├── requirements.txt             # Python dependencies
├── Dockerfile                   # Full python:3.11 image (kaleido requires system libs)
├── railway.toml                 # Railway configuration
└── CLAUDE.md                    # Full architecture and decisions log
```

---

## 9. Environment Variables Reference

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude |
| `OPENAI_API_KEY` | OpenAI API key for embeddings |
| `VOYAGE_API_KEY` | Voyage AI key (only if `EMBEDDING_PROVIDER=voyage`) |
| `EMBEDDING_PROVIDER` | `openai` or `voyage` (default: `openai`) |
| `PINECONE_API_KEY` | Pinecone API key |
| `PINECONE_INDEX_NAME` | Pinecone index name (e.g., `it-assistant`) |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key |
| `DATABASE_URL` | Postgres connection string (for psycopg2 direct queries) |
| `SLACK_BOT_TOKEN` | Slack bot OAuth token (`xoxb-...`) |
| `SLACK_SIGNING_SECRET` | Slack app signing secret |
| `SLACK_APP_TOKEN` | Slack app-level token for socket mode (`xapp-...`) |
| `APP_URL` | Public URL of the deployed app (e.g. Railway URL) — enables interactive Plotly chart links |
| `PORT` | Port to run on (default: `8000`) |
| `ENVIRONMENT` | `development` or `production` |
