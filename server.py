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

# Store tokens and activities
tokens = {}
active_activities = {}

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
        'content-type': 'application/json'
    }
    
    url = f'https://{APNS_HOST}/3/device/{token}'
    
    logger.info(f"Sending push notification to: {url}")
    logger.info(f"Headers: {headers}")
    logger.info(f"Payload: {payload}")
    
    async with httpx.AsyncClient(verify=True) as client:
        try:
            response = await client.post(
                url=url,
                json=payload,
                headers=headers,
                timeout=30.0
            )
            
            logger.info(f"APNs response status: {response.status_code}")
            if response.status_code == 200:
                return {"status": "success"}
            else:
                error_text = response.text
                logger.error(f"APNs error response: {error_text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"APNs error: {error_text}"
                )
        except httpx.RequestError as e:
            logger.error(f"HTTP Request error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Request error: {str(e)}")
        except Exception as e:
            logger.error(f"Error sending push notification: {str(e)}")
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
async def register_token(registration: TokenRegistration):
    """Register a push token for a train"""
    try:
        logger.info(f"Registering token for train {registration.train_id}")
        tokens[registration.push_token] = registration.train_id
        active_activities[registration.push_token] = {}
        logger.info(f"Current tokens: {tokens}")
        return {"status": "Token registered"}
    except Exception as e:
        logger.error(f"Error registering token: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update-train-activity")
async def update_train_activity(update: TrainUpdate):
    """Update train activity status"""
    try:
        logger.info(f"Received update for token: {update.push_token}")
        
        if update.push_token not in tokens:
            logger.error(f"Token not found. Available tokens: {tokens}")
            raise HTTPException(status_code=400, detail="Token not found")
            
        # Store the update
        active_activities[update.push_token] = update.dict()
        logger.info(f"Update stored successfully")
        
        # Create payload for APNs
        payload = {
            "aps": {
                "timestamp": int(time.time()),
                "event": "update",
                "content-state": update.dict(exclude={'push_token'})
            }
        }
        
        return await send_push_notification(update.push_token, payload)
    except Exception as e:
        logger.error(f"Error processing update: {str(e)}")
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

@app.get("/debug/tokens")
async def debug_tokens():
    """Debug endpoint to view registered tokens"""
    return {"tokens": tokens, "activities": active_activities}

@app.on_event("startup")
async def startup_event():
    """Start the periodic update task when the server starts"""
    asyncio.create_task(periodic_updates())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
