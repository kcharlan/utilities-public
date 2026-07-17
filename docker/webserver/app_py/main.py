from fastapi import FastAPI

app = FastAPI()

@app.get("/api/py/hello")
def hello_py():
    return {"ok": True, "from": "python"}
