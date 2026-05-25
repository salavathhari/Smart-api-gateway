"""
Mock AI Service — listens on port 9003.
"""

import uvicorn
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AI Service (Ollama Powered)", version="1.1.0")

# Ollama local configuration
OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.1:latest"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "AI Service is active", "provider": "Ollama (local)", "model": DEFAULT_MODEL}

@app.post("/ai/complete")
async def complete(body: dict):
    prompt = body.get("prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    try:
        print(f"DEBUG: Calling Ollama with prompt length {len(prompt)} and timeout 300.0s")
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": DEFAULT_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": 100,  # Limit output length to speed up
                        "temperature": 0.1   # More deterministic/faster
                    }
                }
            )
            
            print(f"DEBUG: Ollama response: {response.status_code}")
            if response.status_code != 200:
                print(f"DEBUG: Ollama error body: {response.text}")
                return {
                    "error": "Ollama error",
                    "status": response.status_code,
                    "details": response.text
                }

            result = response.json()
            print(f"DEBUG: Ollama json: {result}")
            completion = result.get("response", "")
            
            return {
                "id": "cmpl-ollama",
                "model": DEFAULT_MODEL,
                "prompt": prompt,
                "completion": completion,
                "service": "ai",
            }
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"DEBUG: AI Service Exception: {error_details}")
        return {"error": str(e), "traceback": error_details, "note": "Is Ollama running?"}

@app.get("/ai/health")
async def health():
    return {"service": "ai", "status": "ok", "engine": "ollama"}


@app.post("/ai/embed")
async def embed(body: dict):
    text = body.get("text", "")
    # Return a fake 4-dim embedding
    return {
        "text": text,
        "embedding": [0.12, -0.34, 0.78, 0.56],
        "model": "mock-embed-v1",
        "service": "ai",
    }


@app.get("/ai/models")
async def list_models():
    return {
        "models": [
            {"id": "mock-gpt", "type": "completion"},
            {"id": "mock-embed-v1", "type": "embedding"},
        ]
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9003, log_level="warning")
