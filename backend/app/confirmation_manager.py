import logging
from typing import Dict, Any, Optional
import uuid

logger = logging.getLogger(__name__)

class ConfirmationManager:
    def __init__(self):
        self.pending_confirmations: Dict[str, Dict[str, Any]] = {}
    
    def add_pending_change(self, user_email: str, field: str, old_value: Any, new_value: Any, context: Dict = None) -> str:
        """Add a pending change that needs user confirmation"""
        confirmation_id = str(uuid.uuid4())[:8]
        
        self.pending_confirmations[user_email] = {
            "id": confirmation_id,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "context": context or {},
            "timestamp": None
        }
        
        return confirmation_id
    
    def has_pending_confirmation(self, user_email: str) -> bool:
        """Check if user has pending confirmation"""
        return user_email in self.pending_confirmations
    
    def get_pending_confirmation(self, user_email: str) -> Optional[Dict[str, Any]]:
        """Get pending confirmation for user"""
        return self.pending_confirmations.get(user_email)
    
    def process_confirmation(self, user_email: str, confirmed: bool) -> Optional[Dict[str, Any]]:
        """Process user's confirmation response"""
        if user_email not in self.pending_confirmations:
            return None
        
        pending = self.pending_confirmations[user_email]
        result = {
            "field": pending["field"],
            "old_value": pending["old_value"],
            "new_value": pending["new_value"],
            "confirmed": confirmed,
            "context": pending["context"]
        }
        
       
        del self.pending_confirmations[user_email]
        
        return result
    
    def clear_pending_confirmation(self, user_email: str):
        """Clear pending confirmation without processing"""
        if user_email in self.pending_confirmations:
            del self.pending_confirmations[user_email]
    
    def detect_confirmation_response(self, user_input: str) -> Optional[str]:
        """Detect if user input is a confirmation response"""
        text = user_input.lower().strip()
        
        positive_patterns = [
            "yes", "yeah", "yep", "sure", "ok", "okay", "correct", "right", 
            "update it", "change it", "go ahead", "proceed", "confirm",
            "yes update", "yes change", "that's right", "sounds good"
        ]
          
        negative_patterns = [
            "no", "nope", "don't", "cancel", "wrong", "incorrect",
            "keep original", "don't change", "no thanks", "cancel that"
        ]
      
        if any(pattern in text for pattern in positive_patterns):
            return "positive"
        
        if any(pattern in text for pattern in negative_patterns):
            return "negative"
        
        
        if text.startswith("no") and ("use" in text or "instead" in text or "change to" in text):
            return "conditional"
        
        return None