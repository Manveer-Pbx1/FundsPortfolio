"""
Portfolio data model - represents a portfolio recommendation
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import json
import logging

logger = logging.getLogger(__name__)


class Portfolio:
    """Represents a portfolio recommendation with user answers and recommendations"""
    
    def __init__(
        self,
        user_answers: Dict[str, Any],
        portfolio_id: Optional[str] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None
    ):
        """
        Initialize a Portfolio.
        
        Args:
            user_answers: Dictionary of questionnaire answers
            portfolio_id: UUID (auto-generated if not provided)
            created_at: ISO 8601 timestamp (auto-generated if not provided)
            updated_at: ISO 8601 timestamp (auto-generated if not provided)
        """
        self.portfolio_id = portfolio_id or self._generate_portfolio_id()
        self.created_at = created_at or self._get_iso_timestamp()
        self.updated_at = updated_at or self._get_iso_timestamp()
        self.user_answers = user_answers
        self.calculated_metrics = {}
        self.recommendations = []
    
    @staticmethod
    def _generate_portfolio_id() -> str:
        """
        Generate a unique portfolio ID.
        
        Format: port_YYYYMMDD_UUID8chars
        
        Returns:
            Portfolio ID string
        """
        date_str = datetime.now(timezone.utc).strftime('%Y%m%d')
        uuid_short = str(uuid.uuid4())[:8].lower()
        return f'port_{date_str}_{uuid_short}'
    
    @staticmethod
    def _get_iso_timestamp() -> str:
        """
        Get current timestamp in ISO 8601 format.
        
        Returns:
            ISO 8601 timestamp string
        """
        return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    
    def set_calculated_metrics(self, metrics: Dict[str, Any]) -> None:
        """
        Set calculated metrics (risk profile, categories, etc.).
        
        Args:
            metrics: Dictionary of calculated metrics
        """
        self.calculated_metrics = metrics
        self.updated_at = self._get_iso_timestamp()
    
    def add_recommendation(self, isin: str, name: str, allocation_percent: float, rationale: str) -> None:
        """
        Add a fund recommendation to the portfolio.
        
        Args:
            isin: Fund ISIN code
            name: Fund name
            allocation_percent: Allocation percentage (0-100)
            rationale: Explanation for recommendation
        """
        recommendation = {
            'isin': isin,
            'name': name,
            'allocation_percent': round(allocation_percent, 2),
            'rationale': rationale
        }
        self.recommendations.append(recommendation)
        self.updated_at = self._get_iso_timestamp()
    
    def set_recommendations(self, recommendations: List[Dict]) -> None:
        """
        Set all recommendations at once.
        
        Args:
            recommendations: List of recommendation dictionaries
        """
        self.recommendations = recommendations
        self.updated_at = self._get_iso_timestamp()
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert portfolio to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of portfolio
        """
        return {
            'portfolio_id': self.portfolio_id,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'user_answers': self.user_answers,
            'calculated_metrics': self.calculated_metrics,
            'recommendations': self.recommendations
        }
    
    def to_json(self) -> str:
        """
        Convert portfolio to JSON string.
        
        Returns:
            JSON representation of portfolio
        """
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Portfolio':
        """
        Create a Portfolio from a dictionary.
        
        Args:
            data: Dictionary with portfolio data
        
        Returns:
            Portfolio instance
        """
        portfolio = cls(
            user_answers=data.get('user_answers', {}),
            portfolio_id=data.get('portfolio_id'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )
        portfolio.calculated_metrics = data.get('calculated_metrics', {})
        portfolio.recommendations = data.get('recommendations', [])
        return portfolio
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Portfolio':
        """
        Create a Portfolio from a JSON string.
        
        Args:
            json_str: JSON string representation
        
        Returns:
            Portfolio instance
        """
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        Validate portfolio data.
        
        Returns:
            Tuple of (is_valid: bool, errors: List[str])
        """
        errors = []
        
        # Check required fields
        if not self.portfolio_id:
            errors.append('portfolio_id is required')
        
        if not self.user_answers:
            errors.append('user_answers cannot be empty')
        
        # Check allocations sum to ~100% if recommendations present
        if self.recommendations:
            total_allocation = sum(r.get('allocation_percent', 0) for r in self.recommendations)
            if not (99.5 <= total_allocation <= 100.5):
                errors.append(
                    f'Recommendation allocations must sum to ~100% (got {total_allocation}%)'
                )
        
        return (len(errors) == 0, errors)
    
    def __repr__(self) -> str:
        """String representation of portfolio"""
        return f'Portfolio({self.portfolio_id}, {len(self.recommendations)} recommendations)'
