"""Tests for fund manager and questionnaire loader"""

import pytest
import json
import os
import tempfile
from funds_portfolio.data.fund_manager import FundManager, get_fund_manager
from funds_portfolio.questionnaire.loader import QuestionnaireLoader, get_questionnaire_loader
from funds_portfolio.models.portfolio import Portfolio


# determine paths to JSON files depending on environment (container vs host)
if os.path.exists('/app/funds_database.json'):
    FUND_DB_PATH = '/app/funds_database.json'
else:
    FUND_DB_PATH = os.path.join(os.getcwd(), 'funds_database.json')

if os.path.exists('/app/preferences_schema.json'):
    Q_SCHEMA_PATH = '/app/preferences_schema.json'
else:
    Q_SCHEMA_PATH = os.path.join(os.getcwd(), 'preferences_schema.json')


class TestFundManager:
    """Test FundManager class"""
    
    def test_fund_manager_loads_database(self):
        """Test that FundManager can load funds_database.json"""
        fm = FundManager(FUND_DB_PATH)
        assert fm.is_loaded(), "Fund manager should load successfully"
        assert len(fm.get_all_funds()) > 0, "Should have loaded at least one fund"
    
    def test_get_all_funds(self):
        """Test getting all funds"""
        fm = FundManager(FUND_DB_PATH)
        funds = fm.get_all_funds()
        assert isinstance(funds, list)
        assert len(funds) > 0
        # Each fund should have required fields
        for fund in funds:
            assert 'isin' in fund
            assert 'name' in fund
            assert 'risk_level' in fund
    
    def test_get_fund_by_isin(self):
        """Test fund lookup by ISIN"""
        fm = FundManager(FUND_DB_PATH)
        # Try to find a real fund (from sample data)
        fund = fm.get_fund_by_isin('IE00B4L5Y983')
        assert fund is not None, "Should find iShares MSCI USA fund"
        assert fund['isin'] == 'IE00B4L5Y983'
    
    def test_get_fund_by_isin_case_insensitive(self):
        """Test that ISIN lookup is case-insensitive"""
        fm = FundManager(FUND_DB_PATH)
        fund_upper = fm.get_fund_by_isin('IE00B4L5Y983')
        fund_lower = fm.get_fund_by_isin('ie00b4l5y983')
        assert fund_upper == fund_lower
    
    def test_get_fund_by_isin_not_found(self):
        """Test that non-existent ISIN returns None"""
        fm = FundManager(FUND_DB_PATH)
        fund = fm.get_fund_by_isin('INVALID123')
        assert fund is None
    
    def test_get_funds_by_risk_level(self):
        """Test filtering funds by risk level"""
        fm = FundManager(FUND_DB_PATH)
        for risk_level in [1, 2, 3, 4, 5]:
            funds = fm.get_funds_by_risk_level(risk_level)
            assert isinstance(funds, list)
            for fund in funds:
                assert fund['risk_level'] == risk_level
    
    def test_get_funds_by_asset_class(self):
        """Test filtering funds by asset class"""
        fm = FundManager(FUND_DB_PATH)
        equity_funds = fm.get_funds_by_asset_class('equity')
        bond_funds = fm.get_funds_by_asset_class('bond')
        
        assert isinstance(equity_funds, list)
        assert isinstance(bond_funds, list)
        
        for fund in equity_funds:
            assert fund['asset_class'].lower() == 'equity'
    
    def test_get_metadata(self):
        """Test retrieving metadata"""
        fm = FundManager(FUND_DB_PATH)
        metadata = fm.get_metadata()
        assert isinstance(metadata, dict)
        assert 'version' in metadata
        assert 'last_updated' in metadata


class TestQuestionnaireLoader:
    """Test QuestionnaireLoader class"""
    
    def test_questionnaire_loader_loads_schema(self):
        """Test that QuestionnaireLoader can load preferences_schema.json"""
        ql = QuestionnaireLoader(Q_SCHEMA_PATH)
        assert ql.is_loaded(), "Questionnaire loader should load successfully"
        assert len(ql.get_sections()) > 0, "Should have loaded at least one section"
    
    def test_get_sections(self):
        """Test getting all questionnaire sections"""
        ql = QuestionnaireLoader(Q_SCHEMA_PATH)
        sections = ql.get_sections()
        assert isinstance(sections, list)
        assert len(sections) > 0
        
        # Expected sections
        section_ids = [s['id'] for s in sections]
        assert 'investment_goal' in section_ids
        assert 'risk_approach' in section_ids
        assert 'loss_tolerance' in section_ids
    
    def test_get_section_by_id(self):
        """Test getting a specific section"""
        ql = QuestionnaireLoader(Q_SCHEMA_PATH)
        section = ql.get_section_by_id('investment_goal')
        assert section is not None
        assert section['id'] == 'investment_goal'
        assert 'options' in section
        assert len(section['options']) > 0
    
    def test_validate_valid_answers(self):
        """Test validation of valid user answers"""
        ql = QuestionnaireLoader(Q_SCHEMA_PATH)
        
        valid_answers = {
            'investment_goal': 'retirement',
            'investment_duration': '20_plus_years',
            'monthly_savings': '300_500',
            'investment_knowledge': 'experienced',
            'risk_approach': 'moderate',
            'loss_tolerance': 'high_loss_tolerance',
            'esg_preference': 'no_requirement',
            'etf_preference': 'no_preference'
        }
        
        is_valid, errors = ql.validate_answers(valid_answers)
        assert is_valid, f"Valid answers should pass validation, but got errors: {errors}"
    
    def test_validate_invalid_answers(self):
        """Test validation catches invalid answers"""
        ql = QuestionnaireLoader(Q_SCHEMA_PATH)
        
        invalid_answers = {
            'investment_goal': 'invalid_goal',
            'risk_approach': 'unknown_approach'
        }
        
        is_valid, errors = ql.validate_answers(invalid_answers)
        assert not is_valid, "Invalid answers should fail validation"
        assert len(errors) > 0
    
    def test_validate_missing_required_field(self):
        """Test validation requires mandatory fields"""
        ql = QuestionnaireLoader(Q_SCHEMA_PATH)
        
        incomplete_answers = {
            'investment_goal': 'retirement'
            # Missing many required fields
        }
        
        is_valid, errors = ql.validate_answers(incomplete_answers)
        assert not is_valid, "Incomplete answers should fail validation"
    
    def test_map_answers_to_risk_profile(self):
        """Test mapping answers to risk profile (1-4)"""
        ql = QuestionnaireLoader(Q_SCHEMA_PATH)
        
        # Conservative answers
        conservative = {
            'risk_approach': 'conservative',
            'loss_tolerance': 'low_loss_tolerance'
        }
        risk_profile = ql.map_answers_to_risk_profile(conservative)
        assert risk_profile in [1, 2], "Conservative answers should give low risk profile"
        
        # Aggressive answers
        aggressive = {
            'risk_approach': 'aggressive',
            'loss_tolerance': 'high_loss_tolerance'
        }
        risk_profile = ql.map_answers_to_risk_profile(aggressive)
        assert risk_profile in [3, 4], "Aggressive answers should give high risk profile"


class TestPortfolio:
    """Test Portfolio model"""
    
    def test_portfolio_creation(self):
        """Test creating a new portfolio"""
        answers = {
            'investment_goal': 'retirement',
            'risk_approach': 'moderate'
        }
        portfolio = Portfolio(answers)
        
        assert portfolio.portfolio_id is not None
        assert portfolio.portfolio_id.startswith('port_')
        assert portfolio.created_at is not None
        assert portfolio.user_answers == answers
    
    def test_portfolio_id_generation(self):
        """Test that portfolio IDs are unique"""
        answers = {'test': 'data'}
        p1 = Portfolio(answers)
        p2 = Portfolio(answers)
        
        assert p1.portfolio_id != p2.portfolio_id, "Each portfolio should have unique ID"
    
    def test_portfolio_timestamp_format(self):
        """Test that timestamps are ISO 8601 format"""
        portfolio = Portfolio({})
        
        # Should end with 'Z' (UTC indicator)
        assert portfolio.created_at.endswith('Z')
        assert portfolio.updated_at.endswith('Z')
        
        # Should be parseable
        from datetime import datetime
        datetime.fromisoformat(portfolio.created_at.replace('Z', '+00:00'))
    
    def test_add_recommendation(self):
        """Test adding fund recommendations"""
        portfolio = Portfolio({})
        
        portfolio.add_recommendation(
            isin='IE00B4L5Y983',
            name='iShares MSCI USA UCITS ETF',
            allocation_percent=50,
            rationale='US equity exposure'
        )
        
        assert len(portfolio.recommendations) == 1
        rec = portfolio.recommendations[0]
        assert rec['isin'] == 'IE00B4L5Y983'
        assert rec['allocation_percent'] == 50.0
    
    def test_portfolio_to_dict(self):
        """Test converting portfolio to dictionary"""
        answers = {'goal': 'retirement'}
        portfolio = Portfolio(answers)
        portfolio.add_recommendation('ISIN123', 'Fund Name', 100, 'All in')
        
        data = portfolio.to_dict()
        
        assert 'portfolio_id' in data
        assert 'created_at' in data
        assert 'user_answers' in data
        assert 'recommendations' in data
        assert len(data['recommendations']) == 1
    
    def test_portfolio_to_json(self):
        """Test converting portfolio to JSON string"""
        answers = {'goal': 'retirement'}
        portfolio = Portfolio(answers)
        
        json_str = portfolio.to_json()
        
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert 'portfolio_id' in parsed
        assert parsed['user_answers'] == answers
    
    def test_portfolio_from_dict(self):
        """Test creating portfolio from dictionary"""
        original = Portfolio({'goal': 'retirement'})
        original.add_recommendation('ISIN123', 'Fund', 100, 'Reason')
        
        # Convert to dict and back
        data = original.to_dict()
        restored = Portfolio.from_dict(data)
        
        assert restored.portfolio_id == original.portfolio_id
        assert restored.user_answers == original.user_answers
        assert len(restored.recommendations) == 1
    
    def test_portfolio_from_json(self):
        """Test creating portfolio from JSON string"""
        original = Portfolio({'goal': 'retirement'})
        original.set_calculated_metrics({'risk_profile': 3})
        
        json_str = original.to_json()
        restored = Portfolio.from_json(json_str)
        
        assert restored.portfolio_id == original.portfolio_id
        assert restored.calculated_metrics['risk_profile'] == 3
    
    def test_portfolio_validate_valid(self):
        """Test validation of valid portfolio"""
        portfolio = Portfolio({'goal': 'retirement'})
        portfolio.add_recommendation('ISIN1', 'Fund1', 100, 'All in')
        
        is_valid, errors = portfolio.validate()
        assert is_valid, f"Valid portfolio should pass validation: {errors}"
    
    def test_portfolio_validate_allocation_mismatch(self):
        """Test validation detects allocation mismatch"""
        portfolio = Portfolio({'goal': 'retirement'})
        portfolio.add_recommendation('ISIN1', 'Fund1', 50, 'Half')
        portfolio.add_recommendation('ISIN2', 'Fund2', 30, 'Partial')  # Only 80% total
        
        is_valid, errors = portfolio.validate()
        assert not is_valid, "Portfolio with mismatched allocations should fail"


class TestSingletons:
    """Test singleton instances"""
    
    def test_fund_manager_singleton(self):
        """Test that FundManager singleton works"""
        fm1 = get_fund_manager()
        fm2 = get_fund_manager()
        assert fm1 is fm2, "Should return same instance"
    
    def test_questionnaire_loader_singleton(self):
        """Test that QuestionnaireLoader singleton works"""
        ql1 = get_questionnaire_loader()
        ql2 = get_questionnaire_loader()
        assert ql1 is ql2, "Should return same instance"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
