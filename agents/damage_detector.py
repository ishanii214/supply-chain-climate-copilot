import sys
sys.path.append(".")
from datetime import datetime
from PIL import Image
import os
from io import BytesIO
import numpy as np

class DamageDetector:
    """
    Analyzes parcel images to detect damage.
    Uses color and pattern analysis for the prototype.
    """
    
    def detect_from_path(self, image_path, delivery_id, audit_logger):
        """Analyze an image file for damage"""
        
        if not os.path.exists(image_path):
            return self._no_image_result(delivery_id, audit_logger)
        
        try:
            result = self._analyze_image(image_path)
        except Exception as e:
            result = {"damage_type": "analysis_failed", "confidence": 0.0, "error": str(e)}
        
        decision = {
            "agent": "damage_detector",
            "delivery_id": delivery_id,
            "timestamp": datetime.utcnow().isoformat(),
            "image_path": image_path,
            "damage_type": result["damage_type"],
            "confidence": result["confidence"],
            "action": (
                "REQUEST_IMAGE"
                if result.get("requires_clearer_image", False)
                else ("FLAG_FOR_INSPECTION" if result["confidence"] > 0.6 else "PASS")
            ),
            "flagged": (
                bool(result.get("requires_clearer_image", False))
                or (result["confidence"] > 0.6)
            ),
            "image_blur_score": result.get("blur_score"),
        }
        
        audit_logger.log(decision)
        return decision

    def detect_from_pil_image(self, pil_img: Image.Image, delivery_id, audit_logger):
        """Analyze a PIL Image already loaded in memory."""
        try:
            pil_img = pil_img.convert("RGB")
            result = self._analyze_pil_image(pil_img)
        except Exception as e:
            result = {"damage_type": "analysis_failed", "confidence": 0.0, "error": str(e)}

        decision = {
            "agent": "damage_detector",
            "delivery_id": delivery_id,
            "timestamp": datetime.utcnow().isoformat(),
            "damage_type": result["damage_type"],
            "confidence": result["confidence"],
            "action": (
                "REQUEST_IMAGE"
                if result.get("requires_clearer_image", False)
                else ("FLAG_FOR_INSPECTION" if result["confidence"] > 0.6 else "PASS")
            ),
            "flagged": (
                bool(result.get("requires_clearer_image", False))
                or (result["confidence"] > 0.6)
            ),
            "image_blur_score": result.get("blur_score"),
            "image_grad_var": result.get("grad_var"),
        }
        audit_logger.log(decision)
        return decision

    def detect_from_bytes(self, image_bytes: bytes, delivery_id, audit_logger):
        """Analyze raw image bytes (useful for API and Streamlit)."""
        if not image_bytes:
            return self._no_image_result(delivery_id, audit_logger)
        try:
            pil_img = Image.open(BytesIO(image_bytes))
        except Exception as e:
            # If bytes can't be decoded as an image, request human handling.
            decision = {
                "agent": "damage_detector",
                "delivery_id": delivery_id,
                "timestamp": datetime.utcnow().isoformat(),
                "damage_type": "invalid_image_bytes",
                "confidence": 0.0,
                "error": str(e),
                "action": "REQUEST_IMAGE",
                "flagged": True,
            }
            audit_logger.log(decision)
            return decision

        return self.detect_from_pil_image(pil_img, delivery_id, audit_logger)
    
    def _analyze_image(self, path):
        """Basic image analysis using PIL"""
        img = Image.open(path).convert("RGB")
        img = img.resize((100, 100))  # Resize for speed
        
        pixels = list(img.getdata())
        
        # Count dark pixels (could indicate water damage / stains)
        dark_count = sum(1 for r,g,b in pixels if r < 60 and g < 60 and b < 60)
        dark_ratio = dark_count / len(pixels)
        
        # Count brownish pixels (could indicate moisture damage)
        brown_count = sum(1 for r,g,b in pixels if r > 100 and g < 80 and b < 60)
        brown_ratio = brown_count / len(pixels)
        
        if dark_ratio > 0.3:
            return {"damage_type": "severe_staining_or_crush", "confidence": 0.85}
        elif brown_ratio > 0.2:
            return {"damage_type": "moisture_or_water_damage", "confidence": 0.75}
        elif dark_ratio > 0.1:
            return {"damage_type": "minor_scuffing", "confidence": 0.60}
        else:
            return {"damage_type": "no_visible_damage", "confidence": 0.90}

    def _analyze_pil_image(self, img: Image.Image):
        """Shared core analysis for both disk and in-memory images."""
        img = img.resize((100, 100))  # Resize for speed
        pixels = list(img.getdata())

        # Blur detection (Laplacian variance). Sharp images have high variance;
        # blurry images have near-zero variance.
        gray = np.array(img.convert("L"), dtype=np.float32)
        padded = np.pad(gray, 1, mode="edge")
        lap = (
            padded[0:-2, 1:-1]
            + padded[2:, 1:-1]
            + padded[1:-1, 0:-2]
            + padded[1:-1, 2:]
            - 4.0 * padded[1:-1, 1:-1]
        )
        blur_score = float(lap.var())

        # Second blur signal: variance of gradient magnitude.
        # Some real phone images can have a Laplacian variance that stays
        # deceptively high; gradient-energy is usually more stable.
        gx = np.zeros_like(gray)
        gy = np.zeros_like(gray)
        gx[:, 1:] = gray[:, 1:] - gray[:, :-1]
        gy[1:, :] = gray[1:, :] - gray[:-1, :]
        mag = np.sqrt(gx * gx + gy * gy)
        grad_var = float(mag.var())

        # Demo-friendly thresholds (tuned for our 100x100 resize pipeline).
        # Synthetic check:
        # - sharp lap ~311, grad_var ~256
        # - blur radius~1 lap ~17,  grad_var ~70
        lap_threshold = 100.0
        grad_var_threshold = 120.0
        requires_clearer_image = (blur_score < lap_threshold) or (grad_var < grad_var_threshold)

        # Count dark pixels (could indicate water damage / stains)
        dark_count = sum(1 for r, g, b in pixels if r < 60 and g < 60 and b < 60)
        dark_ratio = dark_count / len(pixels)

        # Count brownish pixels (could indicate moisture damage)
        brown_count = sum(1 for r, g, b in pixels if r > 100 and g < 80 and b < 60)
        brown_ratio = brown_count / len(pixels)

        # If the photo is too blurry, prioritize requesting a clearer image for accuracy.
        if requires_clearer_image:
            return {
                "damage_type": "blurred_photo_unusable",
                "confidence": 0.18,
                "requires_clearer_image": True,
                "blur_score": blur_score,
                "grad_var": grad_var,
            }

        # Otherwise classify using the existing color/ratio heuristics,
        # but slightly down-weight confidence if blur is still borderline.
        sharpness_factor = max(0.35, min(1.0, blur_score / 50.0))

        if dark_ratio > 0.3:
            return {
                "damage_type": "severe_staining_or_crush",
                "confidence": round(0.85 * sharpness_factor, 3),
                "blur_score": blur_score,
                "grad_var": grad_var,
            }
        if brown_ratio > 0.2:
            return {
                "damage_type": "moisture_or_water_damage",
                "confidence": round(0.75 * sharpness_factor, 3),
                "blur_score": blur_score,
                "grad_var": grad_var,
            }
        if dark_ratio > 0.1:
            return {
                "damage_type": "minor_scuffing",
                "confidence": round(0.60 * sharpness_factor, 3),
                "blur_score": blur_score,
                "grad_var": grad_var,
            }
        return {
            "damage_type": "no_visible_damage",
            "confidence": round(0.92 * sharpness_factor, 3),
            "blur_score": blur_score,
            "grad_var": grad_var,
        }
    
    def detect_from_description(self, description, delivery_id, audit_logger):
        """
        When no image is available, use text description from driver notes.
        This is the fallback for the prototype demo.
        """
        description = description.lower()
        
        damage_keywords = {
            "wet": ("water_damage", 0.80),
            "torn": ("torn_packaging", 0.85),
            "crushed": ("crush_damage", 0.90),
            "damp": ("moisture_damage", 0.75),
            "broken": ("structural_damage", 0.88),
            "intact": ("no_damage", 0.92),
            "fine": ("no_damage", 0.88),
            "good": ("no_damage", 0.85)
        }
        
        for keyword, (damage_type, confidence) in damage_keywords.items():
            if keyword in description:
                decision = {
                    "agent": "damage_detector",
                    "delivery_id": delivery_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "method": "text_description",
                    "damage_type": damage_type,
                    "confidence": confidence,
                    "action": "FLAG_FOR_INSPECTION" if confidence > 0.7 and "no" not in damage_type else "PASS",
                    "flagged": confidence > 0.7 and "no" not in damage_type
                }
                audit_logger.log(decision)
                return decision
        
        # Default if no keywords matched
        decision = {
            "agent": "damage_detector",
            "delivery_id": delivery_id,
            "timestamp": datetime.utcnow().isoformat(),
            "method": "text_description",
            "damage_type": "unclassifiable",
            "confidence": 0.0,
            "action": "FLAG_FOR_INSPECTION",
            "flagged": True
        }
        audit_logger.log(decision)
        return decision
    
    def _no_image_result(self, delivery_id, audit_logger):
        decision = {
            "agent": "damage_detector",
            "delivery_id": delivery_id,
            "timestamp": datetime.utcnow().isoformat(),
            "damage_type": "no_image_provided",
            "confidence": 0.0,
            "action": "REQUEST_IMAGE",
            "flagged": False
        }
        audit_logger.log(decision)
        return decision


if __name__ == "__main__":
    class FakeLogger:
        def log(self, data): print("LOG:", data)
    
    agent = DamageDetector()
    # Test with text description
    result = agent.detect_from_description("package is wet and torn", "DEL-99999", FakeLogger())
    print("Result:", result)