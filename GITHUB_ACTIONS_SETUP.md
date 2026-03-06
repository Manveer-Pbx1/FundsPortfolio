# GitHub Actions Setup

This document explains the GitHub Actions CI/CD setup for the FundsPortfolio project.

## Workflows

### 1. Test Workflow (`.github/workflows/test.yml`)
- **Triggers**: Push to `main`/`develop`, PR to `main`
- **Jobs**:
  - `test`: Runs pytest on Ubuntu with Python 3.11

### 2. CI/CD Pipeline (`.github/workflows/ci-cd.yml`)
- **Triggers**: Push to `main`/`develop`, PR to `main`, Manual dispatch
- **Jobs**:
  - `test`: Unit tests with coverage reporting
  - `security-scan`: Trivy vulnerability scanning
  - `build-and-push`: Docker build and push to GHCR
  - `deploy`: Heroku deployment (manual trigger or main branch)

## Required Secrets

Set these in your GitHub repository settings under "Secrets and variables" → "Actions":

### For Docker Registry (GHCR)
- `GITHUB_TOKEN`: Automatically available (no setup needed)

### For Heroku Deployment
- `HEROKU_API_KEY`: Your Heroku API key
- `HEROKU_APP_NAME`: Your Heroku app name (e.g., `funds-portfolio-mvp`)
- `HEROKU_EMAIL`: Email associated with your Heroku account

## Setting Up Secrets

```bash
# Set Heroku secrets
gh secret set HEROKU_API_KEY --body "your-heroku-api-key"
gh secret set HEROKU_APP_NAME --body "your-app-name"
gh secret set HEROKU_EMAIL --body "your-email@example.com"
```

## Environments

The workflow uses these environments:
- `staging`: For manual deployments to staging
- `production`: For production deployments

## Status Badge

Add this to your README.md:

```markdown
[![CI/CD](https://github.com/YOUR_USERNAME/funds-portfolio/actions/workflows/ci-cd.yml/badge.svg?branch=main)](https://github.com/YOUR_USERNAME/funds-portfolio/actions)
```

Replace `YOUR_USERNAME` with your actual GitHub username.

## Local Testing

Test workflows locally using [act](https://github.com/nektos/act):

```bash
# Install act
brew install act  # macOS
# or: curl https://raw.githubusercontent.com/nektos/act/master/install.sh | bash

# Test the test job
act push -j test

# Test the full pipeline
act push
```

## Deployment

### Manual Deployment
1. Go to Actions tab in GitHub
2. Select "CI/CD Pipeline" workflow
3. Click "Run workflow"
4. Choose environment (staging/production)
5. Click "Run workflow"

### Automatic Deployment
- Pushing to `main` branch automatically deploys to staging
- Use manual trigger for production deployments

## Monitoring

- **Actions Tab**: View workflow runs and logs
- **Deployments**: Check Heroku dashboard for app status
- **Security**: Review Trivy scan results in Security tab

## Troubleshooting

### Workflow Not Triggering
- Check branch names match triggers
- Ensure workflow file is in `.github/workflows/`
- Verify YAML syntax

### Docker Build Failing
- Check Dockerfile syntax
- Ensure all required files are copied
- Review build logs for missing dependencies

### Deployment Failing
- Verify Heroku secrets are set correctly
- Check Heroku app exists and is accessible
- Review Heroku logs: `heroku logs --app your-app-name`

### Secrets Issues
- Secrets are masked as `***` in logs
- Re-add secrets if they seem incorrect
- Use repository secrets for repo-specific values