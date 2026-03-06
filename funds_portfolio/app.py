"""Flask application entry point"""

import os
import logging
from flask import Flask, jsonify, render_template, render_template_string

def create_app():
    """Create and configure Flask app"""
    app = Flask(__name__, template_folder='templates')
    
    # Home page
    @app.route('/')
    def index():
        # Try to render the template; fall back if missing
        tpl_path = os.path.join(app.root_path, 'templates', 'index.html')
        if os.path.exists(tpl_path):
            return render_template('index.html')
        logging.warning('index.html template not found at %s, returning fallback HTML', tpl_path)
        return render_template_string(
            '<!doctype html><html><head><title>FundsPortfolio</title></head>'
            '<body><h1>FundsPortfolio API</h1><p>Template missing.</p></body></html>'
        )
    
    # Health check endpoint
    @app.route('/health')
    def health():
        return jsonify({"status": "ok"}), 200
    
    # Questionnaire endpoint (stub)
    @app.route('/api/questionnaire')
    def get_questionnaire():
        return jsonify({"message": "Questionnaire endpoint - Phase 1"}), 200
    
    # Portfolio endpoints (stubs)
    @app.route('/api/portfolio', methods=['POST'])
    def create_portfolio():
        return jsonify({"message": "Create portfolio - Phase 4"}), 200
    
    @app.route('/api/portfolio/<portfolio_id>', methods=['GET'])
    def get_portfolio(portfolio_id):
        return jsonify({"portfolio_id": portfolio_id, "message": "Get portfolio - Phase 4"}), 200
    
    @app.route('/api/funds')
    def get_funds():
        return jsonify({"message": "Get funds - Phase 4"}), 200
    
    # log template folder for debugging
    logging.getLogger('werkzeug').setLevel(logging.INFO)
    app.logger.info('template folder = %s', app.template_folder)
    return app


# Create app instance for gunicorn
app = create_app()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
