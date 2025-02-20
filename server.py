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

# Configuration
TEAM_ID = "7QM8T4XA98"  # Replace with your Apple Team ID
KEY_ID = "54QRS283BA"
BUNDLE_ID = "francescoparadis.Trainss"  # Replace with your app bundle ID
AUTH_KEY_PATH = "Trainss/Resources/AuthKey_54QRS283BA.p8"

# APNs Configuration
APNS_HOST = "api.sandbox.push.apple.com"  # Use api.push.apple.com for production
APNS_PORT = 443

# Store active sessions
active_activities: Dict[str, dict] = {}

class TrainUpdate(BaseModel):
    push_token: str
    ritardo: int
    compOraUltimoRilevamento: str

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
        'apns-priority': '5'
    }

    url = f'https://{APNS_HOST}:{APNS_PORT}/3/device/{token}'
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                return {"status": "success"}
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"APNs error: {response.text}"
                )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

async def periodic_updates():
    """Send updates every 10 seconds to all active live activities."""
    while True:
        for token, data in active_activities.items():
            try:
                payload = {
                    "aps": {
                        "timestamp": int(time.time()),
                        "event": "update",
                        "content-state": {
                            "ritardo": data["ritardo"],
                            "compOraUltimoRilevamento": data["compOraUltimoRilevamento"]
                        },
                        "alert": {
                            "title": "Train Update",
                            "body": f"Delay: {data['ritardo']} minutes"
                        }
                    }
                }
                await send_push_notification(token, payload)
            except Exception as e:
                print(f"Error sending update to {token}: {str(e)}")
        
        await asyncio.sleep(10)  # Wait for 10 seconds before next update

@app.post("/update-train-activity")
async def update_train_activity(update: TrainUpdate):
    """
    Endpoint to send Live Activity updates for train status and store the activity
    """
    # Store or update the activity data
    active_activities[update.push_token] = {
        "ritardo": update.ritardo,
        "compOraUltimoRilevamento": update.compOraUltimoRilevamento
    }

    payload = {
        "aps": {
            "timestamp": int(time.time()),
            "event": "update",
            "content-state": {
                "ritardo": update.ritardo,
                "compOraUltimoRilevamento": update.compOraUltimoRilevamento
            },
            "alert": {
                "title": "Train Update",
                "body": f"Delay: {update.ritardo} minutes"
            }
        }
    }

    return await send_push_notification(update.push_token, payload)

@app.post("/end-train-activity")
async def end_train_activity(update: TrainUpdate):
    """
    Endpoint to end a Live Activity
    """
    if update.push_token in active_activities:
        del active_activities[update.push_token]

    payload = {
        "aps": {
            "timestamp": int(time.time()),
            "event": "end",
            "content-state": {
                "ritardo": update.ritardo,
                "compOraUltimoRilevamento": update.compOraUltimoRilevamento
            }
        }
    }

    return await send_push_notification(update.push_token, payload)

# Test endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.on_event("startup")
async def startup_event():
    """Start the periodic update task when the server starts"""
    asyncio.create_task(periodic_updates())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)



