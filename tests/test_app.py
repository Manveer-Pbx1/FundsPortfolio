"""Tests for Flask application"""

import pytest
from funds_portfolio.app import create_app


@pytest.fixture
def app():
    """Create and configure test app"""
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create test client"""
    return app.test_client()


def test_health_check(client):
    """Test health endpoint"""
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_questionnaire_endpoint(client):
    """Test questionnaire endpoint (stub)"""
    response = client.get('/api/questionnaire')
    assert response.status_code == 200


def test_create_portfolio_endpoint(client):
    """Test portfolio creation endpoint (stub)"""
    response = client.post('/api/portfolio', json={"user_answers": {}})
    assert response.status_code == 200


def test_index_route(client):
    """Index page should return HTML even if template missing"""
    response = client.get('/')
    assert response.status_code == 200
    assert b"<html" in response.data


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
