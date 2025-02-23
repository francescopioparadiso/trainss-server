from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import jwt
import time
import json
import httpx
from typing import Dict
import asyncio
from datetime import datetime
import os

app = FastAPI()

# Configuration
TEAM_ID = "7QM8T4XA98"
KEY_ID = "54QRS283BA"
BUNDLE_ID = "francescoparadis.Trainss"
APNS_HOST = "api.sandbox.push.apple.com"

# Store active sessions
active_activities: Dict[str, dict] = {}

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
        'apns-priority': '10'
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

async def periodic_updates():
    """Send updates every 10 seconds to all active live activities."""
    while True:
        print(f"Running periodic updates for {len(active_activities)} activities")
        current_time = int(time.time())
        
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
        
        await asyncio.sleep(10)

@app.post("/update-train-activity")
async def update_train_activity(update: TrainUpdate):
    """Endpoint to send Live Activity updates for train status"""
    print(f"Received update request for token: {update.push_token}")
    
    try:
        update_dict = update.dict(exclude={'push_token'})
        for key in ['orarioUltimoRilevamento', 'orarioPartenza', 'orarioArrivo']:
            if key in update_dict and update_dict[key]:
                update_dict[key] = update_dict[key] // 1000
        
        active_activities[update.push_token] = update_dict
        
        payload = {
            "aps": {
                "timestamp": int(time.time()),
                "event": "update",
                "content-state": update_dict
            }
        }
        
        print(f"Formatted payload: {json.dumps(payload, indent=2)}")
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
        "active_activities": len(active_activities)
    }

@app.on_event("startup")
async def startup_event():
    """Start the periodic update task when the server starts"""
    asyncio.create_task(periodic_updates())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
