"""
Mock AI Service — listens on port 9003.
"""

import uvicorn
from fastapi import FastAPI

app = FastAPI(title="AI Service (Mock)", version="1.0.0")


@app.get("/ai/health")
async def health():
    return {"service": "ai", "status": "ok"}


@app.post("/ai/complete")
async def complete(body: dict):
    prompt = body.get("prompt", "")
    return {
        "id": "cmpl-mock-001",
        "model": "mock-gpt",
        "prompt": prompt,
        "completion": f"[Mock AI response to: '{prompt[:50]}...']",
        "tokens": {"prompt": len(prompt.split()), "completion": 12},
        "service": "ai",
    }


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
