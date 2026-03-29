class GuardrailEngine:
    """
    Validates inputs and outputs to ensure
    the system behaves safely and correctly.
    """
    
    # Fields that contain personal data — must be redacted
    SENSITIVE_FIELDS = ["driver_name", "driver_phone", "customer_address", "customer_email"]
    
    def clean_input(self, delivery: dict) -> dict:
        """Remove/mask personal data before processing"""
        cleaned = delivery.copy()
        for field in self.SENSITIVE_FIELDS:
            if field in cleaned:
                cleaned[field] = "[REDACTED]"
        return cleaned
    
    def validate_input(self, delivery: dict):
        """Check required fields exist"""
        required = ["delivery_id", "origin_lat", "origin_lon", "dest_lat", "dest_lon"]
        missing = [f for f in required if f not in delivery]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
    
    def validate_output(self, result: dict) -> dict:
        """Check outputs are sensible and add warnings if needed"""
        
        warnings = []
        
        # Check confidence levels
        disruption_confidence = result["disruption"].get("confidence", 1.0)
        if disruption_confidence < 0.6:
            warnings.append("LOW CONFIDENCE: Disruption assessment needs human review")
            result["disruption"]["human_review_required"] = True
        
        # Check delay sanity
        delay_hours = result["delay"].get("predicted_delay_hours", 0)
        if delay_hours > 168:  # More than 1 week
            result["delay"]["predicted_delay_hours"] = 168
            warnings.append("Delay capped at 168 hours (maximum reliable prediction)")
        
        # Critical severity must flag for human review
        if result["disruption"]["severity"] == "CRITICAL":
            warnings.append("CRITICAL SEVERITY: Human approval required before dispatch")
            result["requires_human_approval"] = True
        
        result["guardrail_warnings"] = warnings
        return result