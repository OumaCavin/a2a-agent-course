# Deployment Guide

This guide covers various deployment options for the A2A Multi-Agent System.

---

## Local Deployment

### Quick Start

```bash
# Clone the repository
git clone https://github.com/OumaCavin/a2a-multi-agent-system.git
cd a2a-multi-agent-system

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp Module2/.env.example Module2/.env
# Edit .env with your OPENAI_API_KEY
```

### Running Agents Locally

Each agent runs on a different port. Run these in separate terminals:

```bash
# Terminal 1 - Triage Agent
cd Module2 && python a2a_triage_agent.py

# Terminal 2 - Contract Review Agent
cd Module2 && python a2a_contract_review_agent.py

# Terminal 3 - Compliance Agent
cd Module2 && python a2a_compliance_agent.py

# Terminal 4 - Client Agent
cd Module2 && python a2a_client_agent.py

# Terminal 5 - User interaction
cd Module2 && python user.py
```

---

## Docker Deployment

### Building Docker Image

```bash
cd Module4

# Build the image
docker build -t a2a-multi-agent:latest .

# Run the container
docker run -d \
  --name a2a-agents \
  -p 9999:9999 \
  -p 9998:9998 \
  -p 9997:9997 \
  -p 9996:9996 \
  -e OPENAI_API_KEY=your_api_key \
  -e BEARER_TOKEN=your_token \
  a2a-multi-agent:latest
```

### Docker Compose

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  triage-agent:
    build: .
    ports:
      - "9999:9999"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    networks:
      - a2a-network

  contract-review-agent:
    build: .
    ports:
      - "9998:9998"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    networks:
      - a2a-network

  compliance-agent:
    build: .
    ports:
      - "9997:9997"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    networks:
      - a2a-network

networks:
  a2a-network:
    driver: bridge
```

Run with:
```bash
docker-compose up -d
```

---

## Cloud Platform Deployments

### 1. Railway

1. **Connect GitHub**: Link your repository to Railway
2. **Configure Environment**: Add `OPENAI_API_KEY` in Railway dashboard
3. **Deploy**: Railway auto-detects Python and deploys

```bash
# Railway CLI (optional)
npm install -g @railway/cli
railway login
railway init
railway up
```

### 2. Render

1. **Create Web Service**: Connect GitHub repository
2. **Build Command**: `pip install -r requirements.txt`
3. **Start Command**: `python Module2/a2a_triage_agent.py`
4. **Environment**: Add `OPENAI_API_KEY`

```bash
# Render Blueprint (render.yaml)
services:
  - type: web
    name: triage-agent
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python Module2/a2a_triage_agent.py
    envVars:
      - key: OPENAI_API_KEY
```

### 3. Fly.io

```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Login and init
fly auth login
fly init

# Deploy
fly deploy
```

### 4. AWS Elastic Beanstalk

```bash
# Install EB CLI
pip install awsebcli

# Initialize
eb init -p python-3.11 a2a-multi-agent
eb create production-env

# Deploy
eb deploy
```

### 5. Google Cloud Run

```bash
# Authenticate
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Build and deploy
gcloud run deploy a2a-multi-agent \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

### 6. Azure Container Apps

```bash
# Login
az login

# Create resource group
az group create --name a2a-rg --location eastus

# Create container app
az containerapp create \
  --name a2a-multi-agent \
  --resource-group a2a-rg \
  --image python:3.11-slim \
  --cpu 1 \
  --memory 2 \
  --environment-variables OPENAI_API_KEY=your_key
```

### 7. DigitalOcean App Platform

1. Go to DigitalOcean > Apps > Create App
2. Connect GitHub repository
3. Configure:
   - Build Command: `pip install -r requirements.txt`
   - Run Command: `python Module2/a2a_triage_agent.py`
4. Add environment variables

---

## Production Checklist

- [ ] Set up environment variables (never commit API keys)
- [ ] Configure bearer token authentication
- [ ] Set up logging and monitoring
- [ ] Configure health check endpoints
- [ ] Set up CI/CD pipeline
- [ ] Configure SSL/TLS
- [ ] Set up backup strategy
- [ ] Document API endpoints

---

## Monitoring and Logging

### Health Check Endpoint

All agents expose a health check at:
```
GET http://localhost:9999/health
GET http://localhost:9998/health
GET http://localhost:9997/health
GET http://localhost:9996/health
```

### Structured Logging

Agents output JSON logs for monitoring:

```json
{
  "timestamp": "2024-01-01T12:00:00Z",
  "level": "INFO",
  "agent": "triage-agent",
  "message": "Task completed",
  "task_id": "abc123"
}
```

---

## Security Considerations

1. **Never expose API keys** - Use environment variables
2. **Enable bearer token auth** - In Module 4
3. **Use HTTPS** - In production
4. **Rate limiting** - Implement request throttling
5. **Input validation** - Sanitize all inputs
6. **Audit logging** - Track all requests

---

## Troubleshooting

### Port Already in Use

```bash
# Linux
lsof -i :9999
kill -9 <PID>

# Windows
netstat -ano | findstr :9999
taskkill /F /PID <PID>
```

### Memory Issues

```bash
# Limit Python memory
export PYTHONMALLOC=malloc
export PYTHONGC=1
```

### Network Timeout

Adjust timeout settings in agent configurations if experiencing network issues.

---

## License

Apache License 2.0 - See [LICENSE](../LICENSE) for details.