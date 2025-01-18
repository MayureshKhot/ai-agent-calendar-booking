import os
import logging
from pydub import AudioSegment
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import speech_recognition as sr
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure the "voice_messages" directory exists
if not os.path.exists("voice_messages"):
    os.makedirs("voice_messages")

# Gemini API Configuration
GEMINI_API_KEY = "your_gemini_api_key"
genai.configure(api_key=GEMINI_API_KEY)

# Google Calendar API Configuration
SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = 'credentials.json'

# Initialize Gemini model
model = genai.GenerativeModel('gemini-pro')

# Authenticate Google Calendar API
def authenticate_google_calendar():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)

# Transcribe audio file to text
def transcribe_audio(audio_file):
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_file) as source:
        audio = recognizer.record(source)
    try:
        text = recognizer.recognize_google(audio)
        return text
    except sr.UnknownValueError:
        return "Could not understand audio"
    except sr.RequestError:
        return "API unavailable"

# Analyze intent using Gemini
def analyze_intent(text):
    prompt = f"Analyze the intent of the following text and respond with one of the following: 'list_events', 'create_event', 'delete_event', or 'unknown'. Text: {text}"
    response = model.generate_content(prompt)
    return response.text.strip().lower()

# List today's events
def list_today_events(service):
    now = datetime.utcnow().isoformat() + 'Z'
    tomorrow = (datetime.utcnow() + timedelta(days=1)).isoformat() + 'Z'
    events_result = service.events().list(calendarId='primary', timeMin=now, timeMax=tomorrow, singleEvents=True, orderBy='startTime').execute()
    events = events_result.get('items', [])
    return events

# Create an event
def create_event(service, summary, start_time, end_time, attendees=None):
    event = {
        'summary': summary,
        'start': {'dateTime': start_time, 'timeZone': 'UTC'},
        'end': {'dateTime': end_time, 'timeZone': 'UTC'},
        'attendees': [{'email': email} for email in attendees] if attendees else [],
    }
    event = service.events().insert(calendarId='primary', body=event).execute()
    logger.info(f"Event created: {event.get('htmlLink')}")

# Delete an event
def delete_event(service, event_id):
    service.events().delete(calendarId='primary', eventId=event_id).execute()
    logger.info(f"Event deleted: {event_id}")

# Replace with your Telegram bot token
TELEGRAM_BOT_TOKEN = "your_telegram_bot_token"

# Function to handle voice messages
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Initialize file paths
    file_path = None
    wav_file_path = None

    try:
        # Download the voice message
        file = await update.message.voice.get_file()
        file_path = os.path.join("voice_messages", f"{update.message.from_user.id}.oga")
        await file.download_to_drive(file_path)
        
        # Convert OGA to WAV using pydub
        wav_file_path = os.path.join("voice_messages", f"{update.message.from_user.id}.wav")
        audio = AudioSegment.from_file(file_path, format="ogg")
        audio.export(wav_file_path, format="wav")
        
        # Transcribe the audio
        text = transcribe_audio(wav_file_path)
        await update.message.reply_text(f"Transcribed Text: {text}")
        
        # Analyze intent and perform action
        await process_intent_and_perform_action(update, text)
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        await update.message.reply_text("An error occurred while processing your request.")
    finally:
        # Clean up files
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        if wav_file_path and os.path.exists(wav_file_path):
            os.remove(wav_file_path)

# Function to handle text messages
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Get the text from the user
        text = update.message.text
        await update.message.reply_text(f"Received Text: {text}")
        
        # Analyze intent and perform action
        await process_intent_and_perform_action(update, text)
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        await update.message.reply_text("An error occurred while processing your request.")

# Function to analyze intent and perform action
async def process_intent_and_perform_action(update: Update, text: str):
    intent = analyze_intent(text)
    service = authenticate_google_calendar()
    
    if intent == "list_events":
        events = list_today_events(service)
        if not events:
            await update.message.reply_text("No events found for today.")
        else:
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                await update.message.reply_text(f"{start} - {event['summary']}")
    elif intent == "create_event":
        # Placeholder values
        summary = "Meeting with Team"
        start_time = (datetime.utcnow() + timedelta(hours=1)).isoformat() + 'Z'
        end_time = (datetime.utcnow() + timedelta(hours=2)).isoformat() + 'Z'
        attendees = ["guest1@example.com", "guest2@example.com"]
        create_event(service, summary, start_time, end_time, attendees)
        await update.message.reply_text("Event created successfully.")
    elif intent == "delete_event":
        # Placeholder event ID
        event_id = "your_event_id"
        delete_event(service, event_id)
        await update.message.reply_text("Event deleted successfully.")
    else:
        await update.message.reply_text("Unknown intent or action not supported.")

# Main function
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers for voice and text messages
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.TEXT, handle_text))
    
    application.run_polling()

if __name__ == "__main__":
    main()
