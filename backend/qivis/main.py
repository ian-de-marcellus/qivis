from fastapi import FastAPI

app = FastAPI(
    title="Qivis",
    description=(
        "Research instrument for exploring AI personality, emotion, and behavior"
        " through branching conversation trees"
    ),
    version="0.1.0",
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}
