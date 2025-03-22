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


# trenitalia function
def fetch_parameter(parameter, train_number):
    url = f"http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/cercaNumeroTrenoTrenoAutocomplete/{train_number}"
    timestamp = int(datetime.now().timestamp() * 1000)
    response = requests.get(url)
    data = response.text.strip().split("|")
    station_code = data[1].split("-")[1]

    url = f"http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/andamentoTreno/{station_code}/{train_number}/{timestamp}"
    response = requests.get(url)
    
    train_data = response.json()
    for v in train_data:
        if v == parameter:
            return train_data[v]

app = FastAPI()

# Set up logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.info(f"Starting server with log level: {log_level}")

# Your existing configuration stays the same
TEAM_ID = os.environ.get("TEAM_ID", "7QM8T4XA98")
KEY_ID = os.environ.get("KEY_ID", "54QRS283BA")
BUNDLE_ID = os.environ.get("BUNDLE_ID", "francescoparadis.Trainss")
APNS_HOST = os.environ.get("APNS_HOST", "api.sandbox.push.apple.com")
APNS_PORT = int(os.environ.get("APNS_PORT", "443"))

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
    numeroTreno: Optional[str] = None  # Make it optional with default None

async def create_token():
    """Create a JWT token for APNs authentication."""
    try:
        # Get the base64-encoded auth key from environment variables
        auth_key = os.environ.get('APNS_AUTH_KEY')
        if not auth_key:
            logger.error("APNS_AUTH_KEY environment variable not found")
            raise HTTPException(status_code=500, detail="APNS authentication key not found")
        
        try:
            # Decode base64 key
            key_data = base64.b64decode(auth_key)
            
            # Create JWT token
            token = jwt.encode(
                {
                    'iss': TEAM_ID,
                    'iat': int(time.time())
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
            logger.error(f"Error decoding key or creating JWT: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error creating JWT token: {str(e)}")
    except Exception as e:
        logger.error(f"Error creating JWT token: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating JWT token: {str(e)}")

async def send_push_notification(token: str, payload: dict):
    """Send push notification to APNs."""
    try:
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
                response = await client.post(
                    url=url,
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )

                logger.info(f"APNs response status: {response.status_code}")
                logger.info(f"APNs response body: {response.text}")
                
                if response.status_code == 200:
                    return {"status": "success"}
                else:
                    error_text = response.text
                    logger.error(f"APNs error response: {error_text}")
                    return {
                        "status": "error",
                        "code": response.status_code,
                        "detail": error_text
                    }
            except httpx.RequestError as e:
                logger.error(f"HTTP Request error: {str(e)}")
                return {"status": "error", "detail": f"Request error: {str(e)}"}
            except Exception as e:
                logger.error(f"Error in HTTP request: {str(e)}")
                return {"status": "error", "detail": str(e)}
    except Exception as e:
        logger.error(f"Error sending push notification: {str(e)}")
        return {"status": "error", "detail": str(e)}

async def periodic_updates():
    while True:
        logger.info(f"Running periodic updates for {len(active_activities)} activities")
        for token, data in list(active_activities.items()):
            try:
                if not data:  # Skip if no data is available
                    logger.info(f"No data available for token {token}")
                    continue
                    
                # Create a clean payload without the push_token
                content_state = data.copy()
                if 'push_token' in content_state:
                    del content_state['push_token']

                # Payload overwriting
                content_state["stazioneUltimoRilevamento"] = fetch_parameter('stazioneUltimoRilevamento',content_state['numeroTreno'])
                content_state["oraUltimoRilevamento"] = fetch_parameter('oraUltimoRilevamento',content_state['numeroTreno'])
                content_state["ritardo"] = fetch_parameter('ritardo',content_state['numeroTreno'])
                
                current_time = int(time.time())
                payload = {
                    "aps": {
                        "timestamp": current_time,
                        "event": "update",
                        "content-state": content_state,
                        "relevance-score": 100.0
                    }
                }
                
                logger.info(f"Periodic update payload for token {token}: {json.dumps(payload, indent=2)}")
                result = await send_push_notification(token, payload)
                logger.info(f"Periodic update result: {result}")
                
                # If there was an error, log it but continue with other tokens
                if result.get("status") == "error":
                    logger.error(f"Error sending update to {token}: {result.get('detail')}")
            except Exception as e:
                logger.error(f"Error processing update for token {token}: {str(e)}")
        
        logger.info("Sleeping for 10 seconds before next update cycle")
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
        
        # If numeroTreno is provided, try to fetch real-time data from Trenitalia API
        if update.numeroTreno:
            try:
                logger.info(f"Fetching real-time data for train {update.numeroTreno}")
                
                update_dict['stazioneUltimoRilevamento'] = fetch_parameter('stazioneUltimoRilevamento', update.numeroTreno)
                update_dict['ritardo'] = fetch_parameter('ritardo', update.numeroTreno)
                
                logger.info(f"Updated with real data from Trenitalia API")
            except Exception as e:
                logger.error(f"Error fetching data from Trenitalia API: {str(e)}")
        else:
            # Ensure time values are properly formatted
            current_time = int(time.time())
            
            # If tempoProssimaStazione is 0 or not provided, calculate it based on arrival time
            if update_dict.get('tempoProssimaStazione', 0) == 0 and update_dict.get('orarioArrivo', 0) > 0:
                arrival_time = update_dict.get('orarioArrivo', 0) / 1000  # Convert from milliseconds
                if arrival_time > current_time:
                    update_dict['tempoProssimaStazione'] = max(0, int(arrival_time - current_time))
            
            # Update orarioUltimoRilevamento if not provided or too old
            if update_dict.get('orarioUltimoRilevamento', 0) == 0:
                update_dict['orarioUltimoRilevamento'] = current_time * 1000  # Convert to milliseconds
        
        # Store the updated data
        active_activities[update.push_token] = update_dict
        logger.info(f"Updated active_activities for token {update.push_token}")
        
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
                "relevance-score": 100.0
            }
        }
        
        result = await send_push_notification(update.push_token, payload)
        logger.info(f"Update result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error processing update: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/end-train-activity")
async def end_train_activity(update: TrainUpdate):
    """Endpoint to end a Live Activity"""
    try:
        logger.info(f"Ending activity for token: {update.push_token}")
        
        if update.push_token in active_activities:
            del active_activities[update.push_token]
            logger.info(f"Removed token {update.push_token} from active activities")

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

        result = await send_push_notification(update.push_token, payload)
        logger.info(f"End activity result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error ending activity: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/debug/jwt")
async def debug_jwt():
    """Debug endpoint to test JWT token generation"""
    try:
        token = await create_token()
        return {"token": token}
    except Exception as e:
        logger.error(f"Error generating JWT token: {str(e)}")
        return {"error": str(e)}

@app.on_event("startup")
async def startup_event():
    """Start the periodic update task when the server starts"""
    # Check if APNS_AUTH_KEY is set
    if not os.environ.get('APNS_AUTH_KEY'):
        logger.warning("APNS_AUTH_KEY environment variable is not set. Push notifications will not work!")
    else:
        logger.info("APNS_AUTH_KEY environment variable is set.")
    
    # Log configuration
    logger.info(f"Server configuration: TEAM_ID={TEAM_ID}, KEY_ID={KEY_ID}, BUNDLE_ID={BUNDLE_ID}")
    logger.info(f"APNs Host: {APNS_HOST}:{APNS_PORT}")
    
    # Start periodic updates
    asyncio.create_task(periodic_updates())
    logger.info("Started periodic train updates task")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
