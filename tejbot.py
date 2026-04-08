import discord
import requests
import re
import os

TOKEN = os.getenv("TOKEN")
API_KEY = os.getenv("API_KEY")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if client.user in message.mentions:
        user_message = re.sub(r"<@!?\\d+>", "", message.content).strip()

        if not user_message:
            await message.reply("Say something.")
            return

        await message.channel.typing()

        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

response = requests.post(
    url,
    headers={
        "Content-Type": "application/json",
        "x-goog-api-key": API_KEY
    },
    json={
        "contents": [
            {
                "parts": [
                    {
                        "text": "Your name is TEJ. Reply in English. " + user_message
                    }
                ]
            }
        ]
    }
)

            data = response.json()

            if "candidates" in data:
                reply = data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                reply = "AI not working"

            await message.reply(reply)

        except:
            await message.reply("Error")

client.run(TOKEN)