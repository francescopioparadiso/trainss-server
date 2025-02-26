# Live Activity Push Notification Server

This server handles push notifications for iOS Live Activities in the Trainss app.

## Setup Instructions

1. Create a new web service on Render.com
2. Connect your GitHub repository
3. Configure the following environment variables in Render:
   - `APNS_AUTH_KEY`: Your APNs authentication key (in base64 format)
   - `TEAM_ID`: Your Apple Developer Team ID
   - `KEY_ID`: Your APNs Key ID
   - `BUNDLE_ID`: Your app's bundle identifier

4. Set the following build settings in Render:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn server:app --host 0.0.0.0 --port $PORT`

5. Deploy the service

## Converting .p8 key to base64

To convert your APNs authentication key to base64 format:

```bash
cat AuthKey_XXXXX.p8 | base64
```

Copy the output and set it as the `APNS_AUTH_KEY` environment variable in Render.

## API Endpoints

- POST `/register-token`: Register a device token for Live Activity updates
- POST `/update-train-activity`: Update a Live Activity
- POST `/end-train-activity`: End a Live Activity
- GET `/health`: Health check endpoint
- GET `/debug/tokens`: View registered tokens (debug only)
- POST `/debug`: Debug endpoint for logging

## Testing

You can test the server locally by running:

```bash
uvicorn server:app --reload
```

The server will be available at `http://localhost:8000`. 
