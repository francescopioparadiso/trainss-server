from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import jwt
import time
import json
import httpx
from typing import Optional, Dict
import asyncio
import os
import logging
import base64
import requests
from datetime import datetime, timedelta, timezone
import urllib.parse as urlp
try:
    from urllib.request import urlopen
except ImportError:
    from urllib import urlopen  


def add_minutes(time_str_or_millis, minutes_to_add: int) -> str:
    try:
        # If the input is an int or a string number, treat it as milliseconds
        if isinstance(time_str_or_millis, int) or (isinstance(time_str_or_millis, str) and time_str_or_millis.isdigit()):
            millis = int(time_str_or_millis)
            date_obj = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)  # Convert from UTC
        else:
            # Else, assume it's a "HH:MM" string
            date_obj = datetime.strptime(time_str_or_millis, "%H:%M")
        
        # Adjust for local timezone (use datetime.timezone)
        date_obj = date_obj.replace(tzinfo=timezone(timedelta(hours=1)))
        
        # Add the minutes
        new_time = date_obj + timedelta(minutes=minutes_to_add)
        
        # Convert back to local timezone if necessary
        new_time = new_time.astimezone(timezone(timedelta(hours=1)))
        
        # Return formatted time
        return new_time.strftime("%H:%M")
    except (ValueError, TypeError):
        return None

def how_much_trenitalia(to_time_str: str) -> int:
    try:
        # Get current time in minutes since midnight
        now = datetime.now(timezone(timedelta(hours=0)))
        current_minutes = now.hour * 60 + now.minute

        # Parse the target time
        target_hour, target_minute = map(int, to_time_str.split(":"))
        target_minutes = target_hour * 60 + target_minute

        # Calculate difference
        difference = target_minutes - current_minutes
        if difference < 0:
            difference += 24 * 60  # handle next day case

        return difference
    except (ValueError, IndexError):
        return None
    
def how_much_italo(to_time_str: str) -> int:
    try:
        # Get current time in minutes since midnight
        now = datetime.now(timezone(timedelta(hours=1)))
        current_minutes = now.hour * 60 + now.minute

        # Parse the target time
        target_hour, target_minute = map(int, to_time_str.split(":"))
        target_minutes = target_hour * 60 + target_minute

        # Calculate difference
        difference = target_minutes - current_minutes
        if difference < 0:
            difference += 24 * 60  # handle next day case

        return difference
    except (ValueError, IndexError):
        return None
    
def time_to_millis(time_str: str) -> int:
    try:
        # Get the current date
        today = datetime.now().date()

        # Parse the time string into a datetime object with today's date
        time_obj = datetime.strptime(time_str, "%H:%M")
        time_obj = time_obj.replace(year=today.year, month=today.month, day=today.day)

        # Adjust for local timezone (use datetime.timezone)
        time_obj = time_obj.replace(tzinfo=timezone(timedelta(hours=1)))
        
        # Convert to UTC time zone
        time_obj = time_obj.astimezone(timezone.utc)
        
        # Get the Unix epoch (1970-01-01 00:00:00 UTC)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

        # Calculate the difference in seconds and convert to milliseconds
        delta = time_obj - epoch
        return int(delta.total_seconds() * 1000)
    except ValueError:
        return None


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

def fetch_fermate_info(parameter, train_number):
    fermate_database = fetch_parameter("fermate", train_number)

    if parameter == "prossima_stazione":
        for d in fermate_database:
            stazione = d.get("stazione")
            partenza_reale = d.get("partenzaReale")
            if partenza_reale is None:
                return stazione
    elif parameter == "prossimo_binario":
        for d in fermate_database:
            binarioEffettivoArrivo = d.get("binarioEffettivoArrivoDescrizione")
            binarioProgrammatoArrivo = d.get("binarioProgrammatoArrivoDescrizione")
            binarioEffettivoPartenza = d.get("binarioEffettivoPartenzaDescrizione")
            binarioProgrammatoPartenza = d.get("binarioProgrammatoPartenzaDescrizione")
            partenza_reale = d.get("partenzaReale")
            if partenza_reale is None:
                if binarioEffettivoPartenza is not None:
                    return binarioEffettivoPartenza
                elif binarioProgrammatoPartenza is not None:
                    return binarioProgrammatoPartenza
                elif binarioEffettivoArrivo is not None:
                    return binarioEffettivoArrivo
                elif binarioProgrammatoArrivo is not None:
                    return binarioProgrammatoArrivo
                else:
                    return "-"
                
    elif parameter == "tempo_prossima_stazione":
        ritardo = fetch_parameter("ritardo", train_number)
        for d in fermate_database:
            partenza_teorica = d.get("partenza_teorica")
            arrivo_teorico = d.get("arrivo_teorico")
            partenza_reale = d.get("partenzaReale")
            if partenza_reale is None:
                if arrivo_teorico is not None:
                    return how_much_trenitalia(add_minutes(arrivo_teorico, ritardo))
                elif partenza_teorica is not None:
                    return how_much_trenitalia(add_minutes(partenza_teorica, ritardo))
                else:
                    return 0

# italo functions
def _decode_json (s):
    if s == '':
        return None
    return json.loads(s)

def _decode_lines (s, linefunc):
    if s == '':
        return []
    
    lines = s.strip().split('\n')
    result = []
    for line in lines:
        result.append(linefunc(line))
            
    return result
       
class ItaloAPI:
    def __init__ (self, **options):
        self.base = 'https://italoinviaggio.italotreno.it/api/'
        self.__verbose = options.get('verbose', False)
        self.__urlopen = options.get('urlopen', urlopen)
        self.__plainoutput = options.get('plainoutput', False)
        self.__decoders = {
            'RicercaTrenoService':     _decode_json,
            'RicercaStazioneService':      _decode_json,
        }
        self.__default_decoder = lambda x: x

    def __checkAndDecode(self, function, data):
        decoder = self.__decoders.get(function, self.__default_decoder)
        return decoder(data)
    
    def RicercaStazione_query(self,station='Milano Centrale',station_code='MC_'):
        query='&CodiceStazione='+station_code+'&NomeStazione='+urlp.quote_plus(station)
        return query
    
    def RicercaTreno_query(self,train_number):
        query='&TrainNumber='+str(train_number)
        return query
        
    def call (self, train_number, **options):
        plain = options.get('plainoutput', self.__plainoutput)
        verbose = options.get('verbose', self.__verbose)
        
        query = self.RicercaTreno_query(train_number)
        
        url = self.base + 'RicercaTrenoService' + '?' + query
        
        if verbose:
            print (url)

        req = self.__urlopen(url)
        data = req.read().decode('utf-8')
        
        if plain:
            return data
        else:
            return self.__checkAndDecode ('RicercaTrenoService', data)
        
def fetch_parameter_italo(parameter, train_number):
    data = ItaloAPI().call(train_number)

    if parameter == "stazioneUltimoRilevamento":
        return ""
    if parameter == "orarioUltimoRilevamento":
        for dict in data:
            if dict == "LastUpdate":
                return time_to_millis(data[dict])
    elif parameter == "ritardo":
        for dict in data:
            if dict == "TrainSchedule":
                for key in data[dict]:
                    if key == "Distruption":
                        for keyy in data[dict][key]:
                            if keyy == "DelayAmount":
                                return data[dict][key][keyy]
    elif parameter == "prossimaStazione":
        for dict in data:
            if dict == "TrainSchedule":
                for key in data[dict]:
                    if key == "StazioniNonFerme":
                        for dictt in data[dict][key]:
                            for keyy in dictt:
                                if keyy == "LocationDescription":
                                    return dictt[keyy]
    elif parameter == "prossimoBinario":
        for dict in data:
            if dict == "TrainSchedule":
                for key in data[dict]:
                    if key == "StazioniNonFerme":
                        for dictt in data[dict][key]:
                            for keyy in dictt:
                                if keyy == "ActualArrivalPlatform":
                                    if dictt[keyy] is not None:
                                        return dictt[keyy]
                                    else:
                                        return "-"
    elif parameter == "tempoProssimaStazione":
        delay = 0
        for dict in data:
            if dict == "TrainSchedule":
                for key in data[dict]:
                    if key == "Distruption":
                        for keyy in data[dict][key]:
                            if keyy == "DelayAmount":
                                delay = data[dict][key][keyy]
        for dict in data:
            if dict == "TrainSchedule":
                for key in data[dict]:
                    if key == "StazioniNonFerme":
                        for dictt in data[dict][key]:
                            for keyy in dictt:
                                if keyy == "EstimatedArrivalTime" and dictt[keyy] != "01:00":
                                    return how_much_italo(add_minutes(dictt[keyy], delay))
                            for keyy in dictt:
                                if keyy == "EstimatedDepartureTime" and dictt[keyy] != "01:00":
                                    return how_much_italo(add_minutes(dictt[keyy], delay))



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
    numeroTreno: Optional[str] = None
    provider: str

async def ping_server():
    """Pings the server to keep it active."""
    while True:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("http://127.0.0.1:8000/")
                logger.info(f"Self-ping status: {response.status_code}")
        except Exception as e:
            logger.error(f"Self-ping failed: {str(e)}")
        await asyncio.sleep(300)

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
                if content_state["provider"] == "Trenitalia":
                    content_state["stazioneUltimoRilevamento"] = fetch_parameter('stazioneUltimoRilevamento',content_state['numeroTreno'])
                    content_state["orarioUltimoRilevamento"] = fetch_parameter('oraUltimoRilevamento',content_state['numeroTreno'])
                    content_state["ritardo"] = fetch_parameter('ritardo', content_state['numeroTreno'])
                    content_state["prossimaStazione"] = fetch_fermate_info("prossima_stazione", content_state['numeroTreno'])
                    content_state["prossimoBinario"] = fetch_fermate_info("prossimo_binario", content_state['numeroTreno'])
                    content_state["tempoProssimaStazione"] = fetch_fermate_info("tempo_prossima_stazione", content_state['numeroTreno'])
                else:
                    content_state["stazioneUltimoRilevamento"] = fetch_parameter_italo('stazioneUltimoRilevamento',content_state['numeroTreno'])
                    content_state["orarioUltimoRilevamento"] = fetch_parameter_italo('orarioUltimoRilevamento',content_state['numeroTreno'])
                    content_state["ritardo"] = fetch_parameter_italo('ritardo', content_state['numeroTreno'])
                    content_state["prossimaStazione"] = fetch_parameter_italo("prossimaStazione", content_state['numeroTreno'])
                    content_state["prossimoBinario"] = fetch_parameter_italo("prossimoBinario", content_state['numeroTreno'])
                    content_state["tempoProssimaStazione"] = fetch_parameter_italo("tempoProssimaStazione", content_state['numeroTreno'])

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
    asyncio.create_task(ping_server())

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
