"""Flask configuration"""

import os
from pathlib import Path

class Config:
    """Base configuration"""
    DEBUG = os.getenv('DEBUG', 'False') == 'True'
    TESTING = False
    
    # Paths
    BASE_DIR = Path(__file__).parent.parent
    PORTFOLIOS_DIR = BASE_DIR / 'portfolios'
    REPORTS_DIR = BASE_DIR / 'reports'
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    # Data files
    FUNDS_DB_PATH = BASE_DIR / 'funds_database.json'
    QUESTIONNAIRE_PATH = BASE_DIR / 'preferences_schema.json'


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    FLASK_ENV = 'development'


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    FLASK_ENV = 'production'


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    DEBUG = True


# Select config based on environment
config_name = os.getenv('FLASK_ENV', 'development')
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
}.get(config_name, DevelopmentConfig)
