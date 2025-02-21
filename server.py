from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import jwt
import time
import json
import httpx
from typing import Optional, Dict
import asyncio
from datetime import datetime, timedelta

app = FastAPI()

# Your existing configuration stays the same
TEAM_ID = "7QM8T4XA98"
KEY_ID = "54QRS283BA"
BUNDLE_ID = "francescoparadis.Trainss"
AUTH_KEY_PATH = "AuthKey_54QRS283BA.p8"
APNS_HOST = "api.sandbox.push.apple.com"
APNS_PORT = 443

# Store both active activities and train-token mappings
active_activities: Dict[str, dict] = {}
train_tokens: Dict[str, str] = {}

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

@app.post("/register-token")
async def register_token(registration: TokenRegistration):
    """Register a push token for a train"""
    print(f"Registering token for train {registration.train_id}: {registration.push_token}")
    train_tokens[registration.train_id] = registration.push_token
    if registration.push_token not in active_activities:
        active_activities[registration.push_token] = {}
    return {"status": "success"}

async def periodic_updates():
    """Send updates every 30 seconds to all registered tokens."""
    while True:
        print(f"Running periodic updates for {len(train_tokens)} trains")
        for token in set(train_tokens.values()):  # Use set to avoid duplicate tokens
            if token in active_activities:
                try:
                    data = active_activities[token]
                    if data:  # Only send if we have data
                        payload = {
                            "aps": {
                                "timestamp": int(time.time()),
                                "event": "update",
                                "content-state": data,
                                "alert": {
                                    "title": "Train Update",
                                    "body": f"Delay: {data.get('ritardo', 0)} minutes"
                                }
                            }
                        }
                        await send_push_notification(token, payload)
                except Exception as e:
                    print(f"Error sending update to token {token}: {str(e)}")
        
        await asyncio.sleep(10)

# Your existing functions stay the same
async def create_token():
    """Create a JWT token for APNs authentication."""
    with open(AUTH_KEY_PATH, 'r') as key_file:
        auth_key = key_file.read()

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
        'apns-push-type': 'liveactivity'
    }

    payload = {
        "aps": {
            "timestamp": int(time.time()),
            "event": "update",
            "content-state": payload["aps"]["content-state"],
            "relevance-score": 1.0,
            "stale-date": int(time.time() + 3600),
            "dismissal-date": int(time.time() + 7200)
        }
    }

    url = f'https://{APNS_HOST}:{APNS_PORT}/3/device/{token}'
    print(f"Sending push notification to: {url}")
    print(f"Payload: {payload}")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            print(f"APNs response status: {response.status_code}")
            if response.status_code == 200:
                return {"status": "success"}
            else:
                print(f"APNs error response: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"APNs error: {response.text}"
                )
        except Exception as e:
            print(f"Error sending push notification: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/update-train-activity")
async def update_train_activity(update: TrainUpdate):
    """Endpoint to send Live Activity updates for train status"""
    print(f"Received update request for token: {update.push_token}")
    
    # Store or update the activity data
    active_activities[update.push_token] = update.dict(exclude={'push_token'})
    
    payload = {
        "aps": {
            "timestamp": int(time.time()),
            "event": "update",
            "content-state": update.dict(exclude={'push_token'}),
            "alert": {
                "title": "Train Update",
                "body": f"Delay: {update.ritardo} minutes"
            }
        }
    }
    
    return await send_push_notification(update.push_token, payload)

@app.post("/end-train-activity")
async def end_train_activity(update: TrainUpdate):
    """Endpoint to end a Live Activity"""
    # Remove from both dictionaries
    if update.push_token in active_activities:
        del active_activities[update.push_token]
    
    # Remove from train_tokens if present
    for train_id, token in list(train_tokens.items()):
        if token == update.push_token:
            del train_tokens[train_id]

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
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "active_activities": len(active_activities),
        "registered_tokens": len(train_tokens)
    }

@app.on_event("startup")
async def startup_event():
    """Start the periodic update task when the server starts"""
    asyncio.create_task(periodic_updates())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
