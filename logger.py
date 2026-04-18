import logging
import json
import os
from datetime import datetime

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

def setup_logger(app):
    if not os.path.exists('data'):
        os.makedirs('data')
        
    log_file = 'data/radar_structured.log'
    
    # Create handler
    handler = logging.FileHandler(log_file)
    handler.setFormatter(JsonFormatter())
    
    # Add to app
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    
    app.logger.info("Structured Logging Initialized")
