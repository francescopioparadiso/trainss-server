from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import jwt
import time
import json
import httpx
from typing import Optional, Dict
import asyncio
from datetime import datetime, timedelta
import os

app = FastAPI()

# Your configuration
TEAM_ID = "7QM8T4XA98"
KEY_ID = "54QRS283BA"
BUNDLE_ID = "francescoparadis.Trainss"
AUTH_KEY_PATH = "AuthKey_54QRS283BA.p8"
APNS_HOST = "api.development.push.apple.com"  # Use this for development
APNS_PORT = 443

# Store both active activities and train-token mappings
active_activities: Dict[str, dict] = {}
train_tokens: Dict[str, str] = {}

# Add proper type hints to the models
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

@app.get("/")
async def root():
    """Root endpoint for health check"""
    return {"status": "healthy"}

@app.post("/register-token")
async def register_token(registration: TokenRegistration):
    """Register a push token for a train"""
    print(f"Registering token for train {registration.train_id}: {registration.push_token}")
    train_tokens[registration.train_id] = registration.push_token
    active_activities[registration.push_token] = {}  # Initialize empty state
    return {"status": "success"}

async def periodic_updates():
    """Send updates every 10 seconds to all active live activities."""
    while True:
        print(f"Running periodic updates for {len(active_activities)} activities")
        current_time = int(time.time())  # Get current time in seconds
        
        for token, data in active_activities.items():
            try:
                payload = {
                    "aps": {
                        "timestamp": current_time,
                        "event": "update",
                        "content-state": data
                    }
                }
                await send_push_notification(token, payload)
            except Exception as e:
                print(f"Error sending update to {token}: {str(e)}")
        
        await asyncio.sleep(10)  # Changed to 10 seconds

# Your existing functions stay the same
async def create_token():
    """Create a JWT token for APNs authentication."""
    # Use environment variable instead of file
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
        'apns-priority': '10',  # Changed to high priority (10)
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
            raise HTTPException(status_code=500, detail=f"Request error: {str(e)}")
        except Exception as e:
            print(f"Error sending push notification: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

@app.post("/update-train-activity")
async def update_train_activity(update: TrainUpdate):
    """Endpoint to send Live Activity updates for train status"""
    print(f"Received update request for token: {update.push_token}")
    
    try:
        # Convert millisecond timestamps to seconds
        update_dict = update.dict(exclude={'push_token'})
        for key in ['orarioUltimoRilevamento', 'orarioPartenza', 'orarioArrivo']:
            if key in update_dict and update_dict[key]:
                update_dict[key] = update_dict[key] // 1000  # Convert ms to seconds
        
        # Store or update the activity data
        active_activities[update.push_token] = update_dict
        
        payload = {
            "aps": {
                "timestamp": int(time.time()),  # Current time in seconds
                "event": "update",
                "content-state": update_dict,
                "alert": {
                    "title": "Train Update",
                    "body": f"Delay: {update.ritardo} minutes"
                }
            }
        }
        
        print(f"Formatted payload: {json.dumps(payload, indent=2)}")  # Debug print
        return await send_push_notification(update.push_token, payload)
    except Exception as e:
        print(f"Error in update_train_activity: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/end-train-activity")
async def end_train_activity(update: TrainUpdate):
    """Endpoint to end a Live Activity"""
    try:
        if update.push_token in active_activities:
            del active_activities[update.push_token]
        
        for train_id, token in list(train_tokens.items()):
            if token == update.push_token:
                del train_tokens[train_id]

        payload = {
            "aps": {
                "timestamp": int(time.time()),
                "event": "end",
                "content-state": update.dict(exclude={'push_token'})
            }
        }

        return await send_push_notification(update.push_token, payload)
    except Exception as e:
        print(f"Error in end_train_activity: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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
