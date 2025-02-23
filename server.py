from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import jwt
import time
import json
import httpx
from typing import Optional, Dict
import asyncio
from datetime import datetime, timedelta
import os
import logging

app = FastAPI()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Your existing configuration stays the same
TEAM_ID = "7QM8T4XA98"
KEY_ID = "54QRS283BA"
BUNDLE_ID = "francescoparadis.Trainss"
AUTH_KEY_PATH = "AuthKey_54QRS283BA.p8"  # Updated to match Render's path
APNS_HOST = "api.sandbox.push.apple.com"
APNS_PORT = 443

# Store active sessions
active_activities: Dict[str, dict] = {}

# Pydantic models for request validation
class TokenRegistration(BaseModel):
    train_id: str
    push_token: str

class TrainUpdate(BaseModel):
    push_token: str
    ritardo: int
    problemi: str
    programmato: bool
    tracciato: bool
    prossimaStazione: str
    prossimoBinario: str
    tempoProssimaStazione: int
    stazioneUltimoRilevamento: str
    orarioUltimoRilevamento: int
    stazionePartenza: str
    orarioPartenza: int
    stazioneArrivo: str
    orarioArrivo: int

async def create_token():
    """Create a JWT token for APNs authentication."""
    auth_key = os.environ.get('APNS_AUTH_KEY')
    if not auth_key:
        raise HTTPException(status_code=500, detail="APNS authentication key not found")

    token = jwt.encode(
        {
            'iss': TEAM_ID,
            'iat': time.time()
        },
        auth_key,
        algorithm='ES256',
        headers={
            'kid': KEY_ID
        }
    )
    return token

async def send_push_notification(token: str, payload: dict):
    """Send push notification to APNs."""
    jwt_token = await create_token()
    
    headers = {
        'authorization': f'bearer {jwt_token}',
        'apns-push-type': 'liveactivity',
        'apns-topic': f'{BUNDLE_ID}.push-type.liveactivity',
        'apns-expiration': '0',
        'apns-priority': '10',
        'content-type': 'application/json'  # Add content-type header
    }

    url = f'https://{APNS_HOST}/3/device/{token}'
    print(f"Sending push notification to: {url}")
    print(f"Headers: {json.dumps(headers, indent=2)}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    async with httpx.AsyncClient(verify=True) as client:
        try:
            response = await client.post(
                url, 
                json=payload, 
                headers=headers,
                timeout=30.0
            )
            print(f"APNs response status: {response.status_code}")
            if response.status_code == 200:
                return {"status": "success"}
            else:
                error_text = response.text
                print(f"APNs error response: {error_text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"APNs error: {error_text}"
                )
        except httpx.RequestError as e:
            print(f"HTTP Request error: {str(e)}")
            import traceback
            print(f"Full error trace: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Request error: {str(e)}")
        except Exception as e:
            print(f"Error sending push notification: {str(e)}")
            import traceback
            print(f"Full error trace: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=str(e))

async def periodic_updates():
    """Send updates every 30 seconds to all active live activities."""
    while True:
        print(f"Running periodic updates for {len(active_activities)} activities")
        for token, data in active_activities.items():
            try:
                payload = {
                    "aps": {
                        "timestamp": int(time.time()),
                        "event": "update",
                        "content-state": data,
                        "alert": {
                            "title": "Train Update",
                            "body": f"Delay: {data['ritardo']} minutes"
                        }
                    }
                }
                await send_push_notification(token, payload)
            except Exception as e:
                print(f"Error sending update to {token}: {str(e)}")
        
        await asyncio.sleep(30)  # Increased to 30 seconds to reduce server load

@app.post("/register-token")
async def register_token(request: Request):
    try:
        data = await request.json()
        logger.info(f"Received registration request: {data}")
        
        train_id = data.get("train_id")
        push_token = data.get("push_token")
        
        if not train_id or not push_token:
            raise HTTPException(status_code=400, detail="Missing train_id or push_token")
            
        active_activities[push_token] = {
            "train_id": train_id,
            "push_token": push_token
        }
        logger.info(f"Registered token. Current tokens: {active_activities}")
        return {"status": "Token registered"}
    except Exception as e:
        logger.error(f"Error in register_token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update-train-activity")
async def update_train_activity(request: Request):
    try:
        data = await request.json()
        logger.info(f"Received update request: {data}")
        
        push_token = data.get("push_token")
        if not push_token:
            raise HTTPException(status_code=400, detail="Missing push_token")
            
        if push_token not in active_activities:
            logger.error(f"Token not found. Available tokens: {active_activities}")
            raise HTTPException(status_code=400, detail="Token not found")
        
        # Process update
        active_activities[push_token] = data
        return {"status": "Update processed"}
    except Exception as e:
        logger.error(f"Error in update_train_activity: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/end-train-activity")
async def end_train_activity(update: TrainUpdate):
    """Endpoint to end a Live Activity"""
    if update.push_token in active_activities:
        del active_activities[update.push_token]

    payload = {
        "aps": {
            "timestamp": int(time.time()),
            "event": "end",
            "content-state": update.dict(exclude={'push_token'}),
            "alert": {
                "title": "Journey Completed",
                "body": "Train has reached its destination"
            }
        }
    }

    return await send_push_notification(update.push_token, payload)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": int(time.time()),
        "active_activities": len(active_activities)
    }

@app.post("/debug")
async def debug_endpoint(data: dict):
    """Debug endpoint to log incoming data"""
    print(f"Received data at debug endpoint: {json.dumps(data, indent=2)}")
    return {"status": "received", "data": data}

@app.on_event("startup")
async def startup_event():
    """Start the periodic update task when the server starts"""
    asyncio.create_task(periodic_updates())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
