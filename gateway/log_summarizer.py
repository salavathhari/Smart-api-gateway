import json
import httpx
from typing import List, Dict, Any
from gateway.config import settings
from gateway.logger import logger
from gateway.database import db_manager

class LogSummarizer:
    """
    Day 10: AI Log Summarization
    Analyzes gateway logs stored in MongoDB and uses AI to provide operational insights.
    """

    SYSTEM_PROMPT = """
    You are an AIOps Assistant. Your job is to analyze API Gateway logs and provide a concise operational summary.
    Look for:
    1. High error rates (4xx or 5xx status codes).
    2. Latency spikes (high latency_ms).
    3. Service instability (repeated failures for a specific service).
    4. Notable traffic patterns.

    Logs are provided as a list of JSON objects.
    Respond with a short, professional summary (max 3-4 bullet points).
    If everything looks healthy, say 'System is healthy'.
    """

    async def summarize_recent_logs(self, limit: int = 100) -> str:
        """Fetch logs from MongoDB and summarize them using AI."""
        if db_manager.db is None:
            return "Log summarization unavailable: MongoDB not connected."

        try:
            # 1. Fetch recent logs
            print(f"Day 10 Debug: Fetching logs from {db_manager.db.name}")
            cursor = db_manager.db.logs.find({}, {"_id": 0}).sort("ts", -1).limit(limit)
            print("Day 10 Debug: Cursor created")
            logs = await cursor.to_list(length=limit)
            print(f"Day 10 Debug: Fetched {len(logs)} logs")
            
            if not logs:
                return "No logs available to analyze."

            # 2. Prepare text for AI (COMPACT FORMAT)
            log_text = ""
            for l in logs[:15]:  # Take only 15 logs to be much faster
                status = l.get('status', '???')
                path = l.get('path', '???')
                latency = l.get('latency_ms', 0)
                # Extremely compact: Status Path Latency
                log_text += f"{status} {path} {latency}ms\n"

            # 3. Call AI Service with even higher timeout
            prompt = f"Analyze these {len(logs[:15])} logs briefly:\n{log_text}\nSUMMARY:"
            logger.info(f"Day 10: Requesting AI Ops Summary (Slim Mode)")
            print(f"Day 10 Debug: Calling AI service with {len(log_text)} chars")
            
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        f"{settings.ai_service_url}/ai/complete",
                        json={"prompt": prompt},
                        timeout=180.0  # 3 minutes - Ollama is struggling on this machine
                    )
                    print(f"Day 10 Debug: AI service response status: {response.status_code}")
                    
                    if response.status_code == 200:
                        data = response.json()
                        return data.get("completion", "AI failed to generate a summary.")
                    else:
                        logger.error(f"AI Service returned status {response.status_code}: {response.text}")
                        return f"AI Service error: {response.status_code}"
                except httpx.TimeoutException:
                    logger.error("AI Service Timeout")
                    return "AI Service timeout (Ollama might be slow)."
                except Exception as e:
                    import traceback
                    logger.error(f"AI Service communication error: {str(e)}\n{traceback.format_exc()}")
                    return f"AI communication error: {str(e)}"

        except Exception as e:
            import traceback
            error_msg = f"Log Summarization Error: {repr(e)}\n{traceback.format_exc()}"
            print(error_msg) # Force to console
            logger.error(error_msg)
            return f"Error during analysis: {repr(e)}"

log_summarizer = LogSummarizer()
