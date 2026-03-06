"""
Questionnaire loader - loads and validates preferences_schema.json
"""

import json
import os
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class QuestionnaireLoader:
    """Loads and validates questionnaire schema from JSON"""
    
    def __init__(self, schema_path: str = '/app/preferences_schema.json'):
        """
        Initialize QuestionnaireLoader with path to questionnaire schema.

        Args:
            schema_path: Path to preferences_schema.json file.  Defaults point at
                         container location; falls back to project-root when
                         running tests locally.
        """
        if not os.path.exists(schema_path):
            alt = os.path.join(os.getcwd(), 'preferences_schema.json')
            if os.path.exists(alt):
                logger.debug('using fallback questionnaire schema path %s', alt)
                schema_path = alt
        self.schema_path = schema_path
        self._questionnaire = None
        self._response_schema = None
        self.load_schema()
    
    def load_schema(self) -> bool:
        """
        Load questionnaire schema from JSON file.
        
        Returns:
            True if load successful, False otherwise
        """
        try:
            if not os.path.exists(self.schema_path):
                logger.error('Questionnaire schema not found at %s', self.schema_path)
                return False
            
            with open(self.schema_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self._questionnaire = data.get('questionnaire', {})
            self._response_schema = data.get('response_schema', {})
            
            logger.info('Loaded questionnaire schema from %s', self.schema_path)
            return True
        
        except (json.JSONDecodeError, IOError) as e:
            logger.error('Failed to load questionnaire schema: %s', e)
            return False
    
    def get_questionnaire(self) -> Dict:
        """
        Get the full questionnaire schema.
        
        Returns:
            Questionnaire dictionary with sections and options
        """
        return self._questionnaire or {}
    
    def get_sections(self) -> List[Dict]:
        """
        Get all questionnaire sections.
        
        Returns:
            List of section dictionaries
        """
        return self._questionnaire.get('sections', []) if self._questionnaire else []
    
    def get_section_by_id(self, section_id: str) -> Optional[Dict]:
        """
        Get a single questionnaire section by ID.
        
        Args:
            section_id: Section ID (e.g., 'investment_goal')
        
        Returns:
            Section dictionary if found, None otherwise
        """
        sections = self.get_sections()
        for section in sections:
            if section.get('id') == section_id:
                return section
        return None
    
    def get_response_schema(self) -> Dict:
        """
        Get the response schema (for validation).
        
        Returns:
            Response schema dictionary
        """
        return self._response_schema or {}
    
    def validate_answers(self, user_answers: Dict) -> tuple[bool, List[str]]:
        """
        Validate user answers against questionnaire schema.
        
        Args:
            user_answers: Dictionary of user answers
        
        Returns:
            Tuple of (is_valid: bool, errors: List[str])
        """
        errors = []
        sections = self.get_sections()
        
        for section in sections:
            section_id = section.get('id')
            is_required = section.get('required', False)
            
            # Check if required field is present
            if is_required and section_id not in user_answers:
                errors.append(f'Required field "{section_id}" is missing')
                continue
            
            if section_id not in user_answers:
                continue
            
            user_value = user_answers[section_id]
            section_type = section.get('type')
            options = section.get('options', [])
            valid_values = [opt.get('value') for opt in options]
            
            # Validate based on field type
            if section_type == 'single_select':
                if user_value not in valid_values:
                    errors.append(
                        f'Invalid value "{user_value}" for field "{section_id}". '
                        f'Must be one of: {", ".join(valid_values)}'
                    )
            
            elif section_type == 'multi_select':
                if not isinstance(user_value, list):
                    errors.append(f'Field "{section_id}" must be an array')
                    continue
                
                for val in user_value:
                    if val not in valid_values:
                        errors.append(
                            f'Invalid value "{val}" in field "{section_id}". '
                            f'Must be one of: {", ".join(valid_values)}'
                        )
        
        return (len(errors) == 0, errors)
    
    def map_answers_to_risk_profile(self, user_answers: Dict) -> int:
        """
        Map user answers to a risk profile (1-4).
        
        Risk profile calculation:
        - risk_approach: 1=conservative, 2=moderate_low, 3=moderate, 4=aggressive
        - loss_tolerance: 1=low, 4=high
        - Average of the two (rounded)
        
        Args:
            user_answers: Dictionary of validated user answers
        
        Returns:
            Risk profile (1-4)
        """
        risk_score = 0
        count = 0
        
        # Get risk_approach score
        if 'risk_approach' in user_answers:
            risk_section = self.get_section_by_id('risk_approach')
            if risk_section:
                for opt in risk_section.get('options', []):
                    if opt.get('value') == user_answers['risk_approach']:
                        risk_score += opt.get('risk_profile', 2)
                        count += 1
                        break
        
        # Get loss_tolerance score
        if 'loss_tolerance' in user_answers:
            loss_section = self.get_section_by_id('loss_tolerance')
            if loss_section:
                for opt in loss_section.get('options', []):
                    if opt.get('value') == user_answers['loss_tolerance']:
                        risk_score += opt.get('loss_tolerance_score', 2)
                        count += 1
                        break
        
        # Default to moderate (2.5) if no scores found
        if count == 0:
            return 3
        
        # Average and round (minimum 1, maximum 4)
        avg_risk = risk_score / count
        risk_profile = round(avg_risk)
        return max(1, min(4, risk_profile))
    
    def is_loaded(self) -> bool:
        """
        Check if questionnaire schema is loaded.
        
        Returns:
            True if schema is loaded, False otherwise
        """
        return self._questionnaire is not None


# Singleton instance for application-wide use
_questionnaire_loader_instance = None


def get_questionnaire_loader(schema_path: str = '/app/preferences_schema.json') -> QuestionnaireLoader:
    """
    Get or create the global QuestionnaireLoader instance.
    
    Args:
        schema_path: Path to preferences_schema.json (used on first call)
    
    Returns:
        QuestionnaireLoader singleton instance
    """
    global _questionnaire_loader_instance
    if _questionnaire_loader_instance is None:
        _questionnaire_loader_instance = QuestionnaireLoader(schema_path)
    return _questionnaire_loader_instance
