import json
from typing import Dict, Any, Optional
import httpx
from gateway.config import settings
from gateway.logger import logger

class IntentClassifier:
    """
    Day 9: AI Intent Classifier
    Uses an LLM to map natural language prompts to API services.
    """
    
    SYSTEM_PROMPT = """
    You are an API Gateway Intent Classifier. 
    Your job is to read a user query and determine which microservice it belongs to.
    Available services:
    - 'auth': For login, tokens, password reset, authentication.
    - 'user': For user profiles, list users, user details.
    - 'chat': For messages, conversations, history.
    - 'ai': For ai completion, prompts, embeddings.
    - 'products': For catalog, inventory, reviews.

    Respond ONLY with a JSON object: {"service": "service_name", "confidence": 0.XX}
    """

    def __init__(self):
        # Default to a mock/simulated classifier if no LLM is configured
        self.provider = "simulated"
        if "localhost" not in settings.ai_service_url:
            self.provider = "ollama"

    async def classify(self, query: str) -> Dict[str, Any]:
        """Classify user intent using AI with heuristic fallback."""
        logger.info(f"🧠 AI Classifying query: '{query}'")
        
        # 1. Try Real AI (Ollama via AI Service)
        try:
            prompt = f"{self.SYSTEM_PROMPT}\nUser Query: {query}\nJSON Result:"
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.ai_service_url}/ai/complete",
                    json={"prompt": prompt},
                    timeout=5.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    completion = data.get("completion", "")
                    
                    import json
                    import re
                    json_match = re.search(r'\{.*\}', completion, re.DOTALL)
                    if json_match:
                        parsed = json.loads(json_match.group())
                        if "service" in parsed:
                            return {
                                "service": parsed["service"],
                                "confidence": parsed.get("confidence", 0.95),
                                "source": "REAL_AI"
                            }
        except Exception as e:
            logger.warning(f"AI Service call failed: {e}")

        # 2. Heuristic Fallback (Runs if AI fails OR returns something we don't understand)
        q = query.lower()
        if any(word in q for word in ["user", "profile", "account", "who am i"]):
            return {"service": "user", "confidence": 0.98, "source": "HEURISTIC"}
        if any(word in q for word in ["buy", "product", "price", "order", "shop"]):
            return {"service": "products", "confidence": 0.96, "source": "HEURISTIC"}
        if any(word in q for word in ["login", "token", "auth", "secure", "password"]):
            return {"service": "auth", "confidence": 0.99, "source": "HEURISTIC"}
        if any(word in q for word in ["chat", "message", "talk", "hello", "hi"]):
            return {"service": "chat", "confidence": 0.94, "source": "HEURISTIC"}
        
        # Final fallback - default to AI completion if nothing else matches
        return {"service": "ai", "confidence": 0.85, "source": "FALLBACK"}

intent_classifier = IntentClassifier()
