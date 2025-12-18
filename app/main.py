from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .database import engine, Base
from .routers import twilio, admin, realtime

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Twilio Scenario System")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(twilio.router)
app.include_router(admin.router)
app.include_router(realtime.router)


@app.get("/")
def read_root():
    return {"message": "System is running"}
