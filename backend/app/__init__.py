"""
Kritikos Backend - Flask Application Factory
"""

import os
import warnings

# Suppress multiprocessing resource_tracker warnings (from third-party libraries like transformers)
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


def create_app(config_class=Config):
    """Flask application factory"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False
    
    # Setup logger
    logger = setup_logger('kritikos')
    
    # Only print startup message in reloader process (prevent duplicate logs in debug mode)
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process
    
    if should_log_startup:
        logger.info("=" * 50)
        logger.info("Kritikos Backend Starting...")
        logger.info("=" * 50)
    
    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    # Register simulation process cleanup handler
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("Simulation process cleanup handler registered")
    
    # Request logging middleware
    @app.before_request
    def log_request():
        logger = get_logger('kritikos.request')
        logger.debug(f"Request: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"Request Body: {request.get_json(silent=True)}")
    
    @app.after_request
    def log_response(response):
        logger = get_logger('kritikos.request')
        logger.debug(f"Response: {response.status_code}")
        return response
    
    # Register blueprints
    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    
    # Health check
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'Kritikos Backend'}
    
    if should_log_startup:
        logger.info("Kritikos Backend Started successfully")
    
    return app

