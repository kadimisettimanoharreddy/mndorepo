import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class ContextManager:
    """Simple context management like your sample code"""
    
    def __init__(self):
        self.context_dir = Path("./contexts")
        self.context_dir.mkdir(exist_ok=True)
    
    def _get_context_file(self, user_email: str) -> Path:
        """Get context file path for user"""
        safe_email = user_email.replace("@", "_").replace(".", "_")
        return self.context_dir / f"context_{safe_email}.txt"
    
    def save_to_context(self, user_email: str, role: str, content: str):
        """Save conversation to context.txt file"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            context_entry = f"[{timestamp}] {role.upper()}: {content}\n"
            
            context_file = self._get_context_file(user_email)
            with open(context_file, "a", encoding="utf-8") as f:
                f.write(context_entry)
        except Exception as e:
            logger.error(f"Error saving to context file: {e}")
    
    def load_context(self, user_email: str) -> str:
        """Load existing context from context.txt file"""
        try:
            context_file = self._get_context_file(user_email)
            if context_file.exists():
                with open(context_file, "r", encoding="utf-8") as f:
                    return f.read().strip()
            return ""
        except Exception as e:
            logger.error(f"Error loading context file: {e}")
            return ""
    
    def clear_context(self, user_email: str):
        """Clear context file for user"""
        try:
            context_file = self._get_context_file(user_email)
            if context_file.exists():
                context_file.unlink()
                logger.info(f"Context cleared for {user_email}")
        except Exception as e:
            logger.error(f"Error clearing context file: {e}")
    
    def get_recent_context(self, user_email: str, lines: int = 20) -> str:
        """Get recent context lines"""
        context = self.load_context(user_email)
        if not context:
            return ""
        
        context_lines = context.split('\n')
        recent_lines = context_lines[-lines:] if len(context_lines) > lines else context_lines
        return '\n'.join(recent_lines)