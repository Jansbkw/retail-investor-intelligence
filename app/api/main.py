from fastapi import FastAPI


app = FastAPI(title="Retail Investor Intelligence", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# TODO: add overview, evidence, questions, and grounded-chat endpoints.

