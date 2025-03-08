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
import base64
import requests
from datetime import datetime

app = FastAPI()

# trenitalia functions
def fetch_train_info(train_number):
    url = f"http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/cercaNumeroTrenoTrenoAutocomplete/{train_number}"
    timestamp = int(datetime.now().timestamp() * 1000)
    response = requests.get(url)
    data = response.text.strip().split("|")
    station_code = data[1].split("-")[1]

    url = f"http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/andamentoTreno/{station_code}/{train_number}/{timestamp}"
    response = requests.get(url)
    train_data = response.json()
    return train_data

def fetch_parameter(parameter, train_number):
    train_data = fetch_train_info(train_number)
    for v in train_data:
        if v == parameter:
            return train_data[v]

def fetch_fermate_info(train_number):
    fermate_database = fetch_parameter("fermate", train_number)
    fermate_list = []
    orari_list = []
    for i, dictionary in enumerate(fermate_database):
        if i == 0:
            for ii,v in enumerate(dictionary):
                if ii == 2:
                    fermate_list.append(dictionary[v])
                if ii == 11:
                    orari_list.append(dictionary[v])
        else:
            for ii,v in enumerate(dictionary):
                if ii == 2:
                    fermate_list.append(dictionary[v])
                if ii == 12:
                    orari_list.append(dictionary[v])
    fermate_dict = {}
    for i,ferm in enumerate(fermate_list):
        for ii,orar in enumerate(orari_list):
            if i==ii:
                fermate_dict[ferm] = orar
    return fermate_dict

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Your existing configuration stays the same
TEAM_ID = "7QM8T4XA98"
KEY_ID = "54QRS283BA"
BUNDLE_ID = "francescoparadis.Trainss"
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
    train_id: str
    seat: Optional[str]
    dataPartenza: int
    dataArrivo: int

async def create_token():
    """Create a JWT token for APNs authentication."""
    auth_key = os.environ.get('APNS_AUTH_KEY')
    if not auth_key:
        raise HTTPException(status_code=500, detail="APNS authentication key not found")
    
    try:
        # Decode base64 key
        key_data = base64.b64decode(auth_key)
        
        token = jwt.encode(
            {
                'iss': TEAM_ID,
                'iat': time.time()
            },
            key_data,
            algorithm='ES256',
            headers={
                'kid': KEY_ID,
                'typ': 'JWT'
            }
        )
        return token
    except Exception as e:
        logger.error(f"Error creating JWT token: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating JWT token: {str(e)}")

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
    logger.info(f"Payload: {json.dumps(payload, indent=2)}")
    
    async with httpx.AsyncClient(http2=True, verify=True) as client:
        try:
            logger.info(f"Sending push notification to: {url}")
            
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
                if not data:  # Skip if no data is available
                    print(f"No data available for token {token}")
                    continue
                    
                # Create a clean payload without the push_token
                content_state = data.copy()
                if 'push_token' in content_state:
                    del content_state['push_token']
                
                current_time = int(time.time())
                payload = {
                    "aps": {
                        "timestamp": current_time,
                        "event": "update",
                        "content-state": content_state,
                        "relevance-score": 1.0,
                        "stale-date": current_time + 1800,  # 30 minutes from now
                        "dismissal-date": current_time + 3600  # 1 hour from now
                    }
                }
                
                logger.info(f"Periodic update payload for token {token}: {json.dumps(payload, indent=2)}")
                await send_push_notification(token, payload)
            except Exception as e:
                logger.error(f"Error sending update to {token}: {str(e)}")
        
        await asyncio.sleep(10)

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
            
        # Store the update with all fields
        update_dict = update.dict()
        update_dict["stazioneUltimoRilevamento"] = fetch_parameter("stazioneUltimoRilevamento",8810)
        active_activities[update.push_token] = update_dict
        logger.info(f"Updated active_activities for token {update.push_token}: {json.dumps(update_dict, indent=2)}")
        
        # Create a clean payload without the push_token
        content_state = update_dict.copy()
        if 'push_token' in content_state:
            del content_state['push_token']
        
        # Create payload for APNs
        current_time = int(time.time())
        payload = {
            "aps": {
                "timestamp": current_time,
                "event": "update",
                "content-state": content_state,
                "relevance-score": 1.0,
                "stale-date": current_time + 1800,  # 30 minutes from now
                "dismissal-date": current_time + 3600  # 1 hour from now
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

    # Create a clean payload without the push_token
    content_state = update.dict()
    if 'push_token' in content_state:
        del content_state['push_token']

    current_time = int(time.time())
    payload = {
        "aps": {
            "timestamp": current_time,
            "event": "end",
            "content-state": content_state,
            "dismissal-date": current_time  # End immediately
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
