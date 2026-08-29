import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
import os

from app.api.websockets import router as ws_router
from app.core.config import settings

app = FastAPI(title="The Chaos Bunker - API")

# Include WebSocket routes
app.include_router(ws_router)

# Temporary route to serve the frontend index.html.
# Adjust the path depending on where the frontend is located.
@app.get("/")
async def get_index():
    # Assumes execution from the /backend folder
    html_path = os.path.join(os.path.dirname(__file__), "../../frontend/index.html")
    return FileResponse(html_path)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.PORT, reload=True)