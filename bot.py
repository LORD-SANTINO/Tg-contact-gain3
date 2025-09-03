import os
import json
import random
import vobject
import asyncio
from telethon import TelegramClient, events, functions, types
from telethon.tl.types import InputPhoneContact, InputUser

# Your API credentials (from my.telegram.org)
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")  # Your Telegram phone for userbot session

SESSIONS_DIR = "sessions"
user_folder = os.path.join(SESSIONS_DIR, PHONE)
if not os.path.exists(user_folder):
    os.makedirs(user_folder)

client = TelegramClient(os.path.join(user_folder, f"{PHONE}.session"), API_ID, API_HASH)

# Store uploaded contacts and requests in memory or files
contacts = []
current_channel = None
requests_channel = '@YourRequestChannelHere'  # where main bot sends requests

# Start the client
async def main():
    await client.start(phone=PHONE)
    print("Userbot started.")

    @client.on(events.NewMessage(chats=requests_channel))
    async def on_request(event):
        text = event.raw_text
        print(f"Received request:\n{text}\n---")
        # You can parse order_id, user id, channel, number here for display or processing.

    @client.on(events.NewMessage(pattern='/upload_vcf'))
    async def upload_vcf(event):
        await event.respond("Please send the .vcf file as a document backup now.")

        @client.on(events.NewMessage(from_users=event.sender_id, incoming=True))
        async def on_vcf_upload(vcf_event):
            if not vcf_event.file or not vcf_event.file.name.endswith('.vcf'):
                await vcf_event.respond("That doesn't seem like a .vcf file. Please send a valid .vcf file.")
                return
            path = os.path.join(user_folder, "contacts.vcf")
            await client.download_media(vcf_event.media, path)
            global contacts
            contacts = []
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for vcard in vobject.readComponents(f):
                    if hasattr(vcard, 'fn') and hasattr(vcard, 'tel'):
                        name = vcard.fn.value
                        for tel in vcard.tel_list:
                            phone = tel.value.replace(" ", "").replace("-", "")
                            if phone.startswith("+"):
                                contacts.append({"name": name, "phone": phone})
            await vcf_event.respond(f"VCF contacts imported: {len(contacts)}")
            client.remove_event_handler(on_vcf_upload)

    @client.on(events.NewMessage(pattern='/setchannel (.+)'))
    async def set_channel(event):
        global current_channel
        current_channel = event.pattern_match.group(1).strip()
        await event.respond(f"Channel set to {current_channel}")

    @client.on(events.NewMessage(pattern='/addmembers (.+)'))
    async def add_members_command(event):
        order_id = event.pattern_match.group(1).strip()
        # Lookup request, parse channel and number from your saved requests if needed
        if not current_channel or not contacts:
            await event.respond("Please upload contacts with /upload_vcf and set channel with /setchannel first.")
            return
        await event.respond(f"Starting to add members for order {order_id}...")
        # Fetch entity and invite logic here (see below)

        entity = await client.get_entity(current_channel)
        # Example batching invite
        for i in range(0, len(contacts), 10):
            batch = contacts[i:i+10]
            input_users = []
            for c in batch:
                input_users.append(InputPhoneContact(client_id=random.randint(1, 99999999), phone=c['phone'], first_name=c['name'], last_name=""))
            result = await client(functions.contacts.ImportContactsRequest(input_users))
            users_to_invite = []
            for user in result.users:
                if hasattr(user, "id") and hasattr(user, "access_hash"):
                    users_to_invite.append(InputUser(user_id=user.id, access_hash=user.access_hash))
            if users_to_invite:
                try:
                    await client(functions.channels.InviteToChannelRequest(channel=entity, users=users_to_invite))
                    await event.respond(f"Invited {len(users_to_invite)} members in batch.")
                    await asyncio.sleep(30)  # Pause to avoid flood
                except Exception as e:
                    await event.respond(f"Error inviting batch: {e}")
                    break
        await event.respond("Adding members completed!")

    await client.run_until_disconnected()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
