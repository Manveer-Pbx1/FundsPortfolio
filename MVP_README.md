# FundsPortfolio MVP – Quick Start Guide

## 📌 Overview

**FundsPortfolio** is a portfolio recommendation engine that:
1. Asks users 7 questions about investment goals, risk tolerance, and experience
2. Recommends a diversified fund portfolio from a database of ~200 funds
3. Stores portfolio recommendations by UUID (anonymous, no personal data)
4. Provides REST API for both GUI and machine access

**MVP Status:** Foundation phase – Docker local dev ready; GitHub Actions pipeline; KIID retrieval script

---

## 🚀 Quick Start (5 minutes)

### Prerequisites
- Docker & Docker Compose installed
- Python 3.11+ (for local testing without Docker)
- Git

### Local Development

```bash
# Clone repo
git clone https://github.com/LowFatMatt/FundsPortfolio.git
cd FundsPortfolio

# Start services
docker compose up --build # I seen to have the CE Version of docker

# Test API
curl http://localhost:5000/health
curl http://localhost:5000/api/questionnaire
```

**Access UI:** http://localhost:5000

---

## 📂 Project Structure (MVP)

```
funds-portfolio/
├── funds_portfolio/           # Main application
│   ├── __init__.py
│   ├── app.py                 # Flask app entry point
│   ├── data/
│   │   ├── fund_manager.py    # Load funds_database.json
│   │   └── price_fetcher.py   # yfinance wrapper
│   ├── portfolio/
│   │   ├── calculator.py      # Sharpe Ratio calculations
│   │   └── optimizer.py       # Portfolio weighting
│   ├── questionnaire/
│   │   └── loader.py          # Load preferences_schema.json
│   ├── api/
│   │   └── routes.py          # Flask endpoints
│   └── models/
│       └── portfolio.py       # Portfolio data model
├── config/
│   └── settings.py            # Flask config
├── templates/                 # HTML/JS frontend
│   ├── index.html
│   └── static/
├── tests/
│   └── test_*.py
├── scripts/
│   └── fetch_kiids.py         # KIID retrieval tool
├── reports/                   # QS output (auto-created)
├── portfolios/                # Stored portfolios (auto-created, .gitignore)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .github/workflows/
│   ├── ci-cd.yml              # GitHub Actions
│   └── deploy.yml             # Heroku deployment
├── funds_database.json        # ~200 funds with KIID URLs
├── preferences_schema.json    # Questionnaire definition
├── isins_sample.txt           # Test ISIN list
├── README.md                  # This file
├── IMPLEMENTATION_SPEC.md     # Technical details
└── DEVOPS_GUIDE.md            # Docker + GitHub Actions guide
```

---

## 🔑 Key Files Explained

### funds_database. json (~200 funds)
```json
{
  "funds_database": [
    {
      "isin": "IE00B4L5Y983",
      "name": "iShares MSCI USA UCITS ETF",
      "provider": "iShares",
      "kiid_url": "https://...",
      "kiid_status": "pending|verified|failed",
      "risk_level": 5,
      "asset_class": "equity",
      "yearly_fee": 0.07
    }
  ]
}
```

### preferences_schema.json (Questionnaire)
Defines 7 questions + possible answers (loaded dynamically by frontend).  
Maps user answers → portfolio calculations.

### Example Portfolio Response
```json
{
  "portfolio_id": "port_20260304_a1b2c3d4e5f6",
  "created_at": "2026-03-04T10:30:00Z",
  "user_answers": {
    "investment_goal": "retirement",
    "investment_duration": "20_plus_years",
    "risk_approach": "moderate"
  },
  "recommendations": [
    {
      "isin": "IE00B4L5Y983",
      "name": "iShares MSCI USA UCITS ETF",
      "allocation_percent": 30,
      "rationale": "US equity exposure for long-term growth"
    }
  ]
}
```

---

## 🛠️ API Endpoints (MVP)

```
GET /health
  → Simple health check: { "status": "ok" }

GET /api/questionnaire
  → Returns preferences_schema.json (all questions + options)

POST /api/portfolio
  Body: { "user_answers": { "investment_goal": "...", ... } }
  → Creates new portfolio, returns portfolio_id + recommendations

GET /api/portfolio/{portfolio_id}
  → Retrieve saved portfolio (from portfolios/{id}.json)

PUT /api/portfolio/{portfolio_id}
  Body: { "user_answers": {...} }
  → Update answers, recalculate, save

GET /api/funds
  → Returns funds_database.json (for debugging)
```

---

## 📊 Workflow: ISIN → KIID → Portfolio

```
1. Admin loads 200 ISINs into funds_database.json
2. Run: python scripts/fetch_kiids.py --isin-file isins_sample.txt
   → Retrieves KIID URLs via iShares search redirects
   → Generates QS report (verified/pending/failed)
3. Manual QS: Review pending ISINs, verify URLs work
4. Update funds_database.json with kiid_status
5. Backend calculates Sharpe Ratio for each fund
6. When user submits questionnaire:
   → Filter funds by risk profile
   → Optimize allocation using scipy.optimize
   → Return portfolio with ISINs + allocations %
```

---

## 🔄 KIID Retrieval (Semi-Manual QS)

### Automated Retrieval

```bash
# Test on 20 sample ISINs
python scripts/fetch_kiids.py \
  --isin-file isins_sample.txt \
  --sample 20 \
  --output reports/ \
  --timeout 10

# Output files:
# - reports/kiid_retrieval_*.json    (full results)
# - reports/kiid_qc_checklist_*.md   (manual review checklist)
# - reports/kiid_verified_*.csv      (for importing)
```

### Manual QS Process

1. Review `reports/kiid_qc_checklist_*.md`
2. For each "Pending" ISIN:
   - Search iShares manually: https://www.ishares.com/uk/individual/en/search
   - Verify KIID URL works (can you download PDF?)
   - Add to funds_database.json with `kiid_status: "verified"`
3. For "Failed" ISINs: Investigate or skip (mark as `failed`)
4. Document notes in `funds_database.json` `notes` field

---

## 🐳 Docker Development

### Build & Run

```bash
docker-compose up --build

# View logs
docker-compose logs -f funds-api

# Stop
docker-compose down

# Restart
docker-compose restart
```

### Volumes (Local Dev)

- `./funds_portfolio/` → `/app/funds_portfolio`
- `./portfolios/` → `/app/portfolios` (persists across restarts)
- `./config/` → `/app/config`

Edit Python files locally → Changes auto-load (Flask debug mode).

### Production Deployment (Heroku)

```bash
# Build Docker image
docker build -t funds-portfolio:latest .

# Test locally with production settings
docker run -e FLASK_ENV=production -p 5000:5000 funds-portfolio:latest

# Push to Heroku
heroku container:push web -a funds-portfolio-mvp
heroku container:release web -a funds-portfolio-mvp
```

---

## 🔄 GitHub Actions CI/CD

### What It Does

1. **On every push:** Run tests + linting
2. **On PR:** Block merge if tests fail
3. **On main branch:** Build + push Docker image to GHCR
4. **Manual trigger:** Deploy to Heroku (optional)

### Setup

```bash
# 1. Add workflow files (already created)
ls .github/workflows/
#   ci-cd.yml
#   deploy.yml

# 2. Set GitHub secrets
goto Settings → Secrets and Variables → Actions
# Add:
#   HEROKU_API_KEY
#   HEROKU_EMAIL
#   HEROKU_APP_NAME

# 3. Push to trigger
git push origin main
```

### Monitor

- Go to repo → Actions tab
- Watch pipeline run
- Review logs if failures

---

## 📋 MVP Implementation Phases

| Phase | Timeline | Deliverable |
|-------|----------|-------------|
| 1: Foundation | Weeks 1-2 | Flask skeleton + JSON loaders + Docker |
| 2: KIID Retrieval | Week 3 | fetch_kiids.py script + QS reports |
| 3: Calculation Engine | Weeks 4-5 | Sharpe Ratio + optimizer + tests |
| 4: API & Frontend | Week 6 | REST endpoints + HTML questionnaire |
| 5: CI/CD & Deploy | Week 7 | GitHub Actions + Heroku Docker |

---

## 🔒 Security (MVP)

✅ **Anonymous portfolios:** No sign-up, no personal data, UUID-based storage  
✅ **HTTPS only:** Enforced by Heroku  
✅ **No secrets in repo:** Use GitHub secrets for API keys  
✅ **Docker image scanning:** Trivy in GitHub Actions  
✅ **Rate limiting:** TODO (post-MVP)  

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v --cov=funds_portfolio

# Run specific test
pytest tests/test_calculator.py::test_sharpe_ratio -v

# Run with coverage report
pytest tests/ --cov=funds_portfolio --cov-report=html
# Open htmlcov/index.html
```

---

## 🐛 Troubleshooting

### Docker build fails
```bash
docker-compose down -v  # Clear volumes
docker-compose up --build --no-cache
```

### Port 5000 already in use
```bash
docker-compose down
# Or change port in docker-compose.yml: 5001:5000
```

### portfolios/ directory missing
```bash
mkdir -p portfolios
# docker-compose will create it, but you can pre-create
```

### Template not found or empty reply
If the homepage returns an empty reply or you see `TemplateNotFound` errors in the logs, the container may be running without the `templates/` directory mounted. The app now falls back to a minimal HTML page, but to restore the full UI
```bash
# make sure you start compose from project root
cd /home/mrick/projects
# rebuild so image includes templates
docker compose up --build
```
### KIID retrieval returns 0 results
```bash
# Check network connectivity
curl -I https://www.ishares.com/uk/individual/en/search?searchTerm=IE00B4L5Y983

# Check ISIN format (must be 12 chars, uppercase)
# Increase delay between requests: --delay 2.0
```

---

## 📖 Further Reading

- [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) – Technical deep-dive
- [DEVOPS_GUIDE.md](DEVOPS_GUIDE.md) – Docker + GitHub Actions setup
- [funds_database.json](funds_database.json) – Fund database schema
- [preferences_schema.json](preferences_schema.json) – Questionnaire definition

---

## 🤝 Contributing

1. Create feature branch: `git checkout -b feature/xyz`
2. Make changes + test: `pytest tests/ -v`
3. Commit: `git commit -m "feat: add xyz"`
4. Push: `git push origin feature/xyz`
5. Open PR (GitHub Actions will test automatically)

---

## 📞 Support

For issues, see:
- GitHub Issues tab
- Logs: `docker-compose logs -f`
- Heroku logs: `heroku logs --tail -a funds-portfolio-mvp`

---

**Last Updated:** 4. März 2026  
**MVP Status:** Phase 1 (Foundation) – Ready for development  
**License:** MIT
