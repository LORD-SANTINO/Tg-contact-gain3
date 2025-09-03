import os
import json
import random
import vobject
import asyncio
import logging
import re
from datetime import datetime
from telethon import TelegramClient, events, functions, types
from telethon.tl.types import InputPhoneContact, InputUser
from telethon.errors import FloodWaitError, UserPrivacyRestrictedError
from telethon.tl.types import Channel, User

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Your API credentials (from my.telegram.org)
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")  # Your Telegram phone for userbot session

# Validate environment variables
if not all([API_ID, API_HASH, PHONE]):
    raise ValueError("Please set API_ID, API_HASH, and PHONE environment variables")

SESSIONS_DIR = "sessions"
user_folder = os.path.join(SESSIONS_DIR, PHONE)
if not os.path.exists(user_folder):
    os.makedirs(user_folder)

# File paths for persistence
CONTACTS_FILE = os.path.join(user_folder, "contacts.json")
REQUESTS_FILE = os.path.join(user_folder, "requests.json")

# Load persistent data
def load_data():
    contacts = []
    requests = {}
    
    if os.path.exists(CONTACTS_FILE):
        try:
            with open(CONTACTS_FILE, 'r') as f:
                contacts = json.load(f)
        except:
            pass
            
    if os.path.exists(REQUESTS_FILE):
        try:
            with open(REQUESTS_FILE, 'r') as f:
                requests = json.load(f)
        except:
            pass
            
    return contacts, requests

# Save persistent data
def save_data(contacts, requests):
    with open(CONTACTS_FILE, 'w') as f:
        json.dump(contacts, f)
    
    with open(REQUESTS_FILE, 'w') as f:
        json.dump(requests, f)

# Initialize
contacts, requests = load_data()
current_channel = None
requests_channel = '@requestmembersbot'  # where main bot sends requests

client = TelegramClient(os.path.join(user_folder, f"{PHONE}.session"), API_ID, API_HASH)

# Parse request message from the main bot
def parse_request(text):
    """Parse request message from the main bot"""
    data = {}
    lines = text.split('\n')
    
    for line in lines:
        if 'Order ID:' in line:
            data['order_id'] = line.split(': ')[1].strip()
        elif 'User ID:' in line:
            data['user_id'] = line.split(': ')[1].strip()
        elif 'Channel:' in line:
            data['channel'] = line.split(': ')[1].strip()
        elif 'Members Requested:' in line:
            data['members_requested'] = int(line.split(': ')[1].strip())
    
    return data

# Store active VCF upload sessions
vcf_upload_sessions = {}

# Command handlers
async def handle_upload_vcf(event):
    # Store that this user is expecting a VCF file
    vcf_upload_sessions[event.sender_id] = True
    await event.reply("Please send the .vcf file as a document now.")

async def handle_vcf_file(event):
    # Check if this user is expecting a VCF file
    if event.sender_id not in vcf_upload_sessions:
        return
        
    # Remove from sessions so we don't process this again
    del vcf_upload_sessions[event.sender_id]
    
    # Check if this is a document
    if not event.document:
        await event.reply("Please send a file, not text.")
        return
        
    # Check if it's a VCF file
    document = event.document
    is_vcf = False
    
    # Check file attributes
    for attr in document.attributes:
        if hasattr(attr, 'file_name') and attr.file_name:
            if attr.file_name.lower().endswith('.vcf'):
                is_vcf = True
                break
    
    if not is_vcf:
        await event.reply("That doesn't seem like a .vcf file. Please send a valid .vcf file.")
        return
        
    path = os.path.join(user_folder, "contacts.vcf")
    await event.reply("Downloading VCF file...")
    
    # Download the file
    try:
        await event.download_media(file=path)
    except Exception as e:
        await event.reply(f"❌ Error downloading file: {e}")
        return
        
    global contacts
    contacts = []
    successful, failed = 0, 0
    
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            # Reset file pointer
            f.seek(0)
            
            for vcard in vobject.readComponents(f):
                try:
                    if hasattr(vcard, 'fn') and hasattr(vcard, 'tel'):
                        name = vcard.fn.value
                        for tel in vcard.tel_list:
                            phone = tel.value.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                            if phone.startswith("+"):
                                contacts.append({"name": name, "phone": phone})
                                successful += 1
                except Exception as e:
                    failed += 1
                    logger.error("Error parsing vcard: %s", e)
        
        save_data(contacts, requests)
        await event.reply(
            f"✅ VCF contacts imported successfully!\n"
            f"• Imported: {successful} contacts\n"
            f"• Failed: {failed} contacts\n"
            f"Use /listcontacts to view imported contacts."
        )
    except Exception as e:
        await event.reply(f"❌ Error processing VCF file: {e}")

async def handle_set_channel(event):
    match = re.search(r'/setchannel\s+(.+)', event.raw_text)
    if not match:
        await event.reply("Usage: /setchannel @channelname")
        return
        
    global current_channel
    channel_input = match.group(1).strip()
    
    try:
        # Try to resolve the channel/group
        entity = await client.get_entity(channel_input)
        current_channel = entity
        await event.reply(f"✅ Channel set to: {getattr(entity, 'title', 'Unknown')}")
    except Exception as e:
        await event.reply(f"❌ Error setting channel: {e}")

async def handle_list_contacts(event):
    if not contacts:
        await event.reply("No contacts imported yet. Use /upload_vcf first.")
        return
        
    message = f"📱 Imported Contacts: {len(contacts)}\n\n"
    for i, contact in enumerate(contacts[:10], 1):
        message += f"{i}. {contact['name']}: {contact['phone']}\n"
        
    if len(contacts) > 10:
        message += f"\n... and {len(contacts) - 10} more contacts."
        
    await event.reply(message)

async def handle_list_requests(event):
    if not requests:
        await event.reply("No requests received yet.")
        return
        
    message = "📋 Pending Requests:\n\n"
    for order_id, req in requests.items():
        if req.get('status') == 'pending':
            message += f"• Order {order_id}: {req.get('members_requested', 0)} members to {req.get('channel', 'Unknown')}\n"
            
    await event.reply(message or "No pending requests.")

async def handle_process_request(event):
    match = re.search(r'/process\s+(\S+)', event.raw_text)
    if not match:
        await event.reply("Usage: /process ORDER_ID")
        return
        
    order_id = match.group(1).strip()
    
    if order_id not in requests:
        await event.reply(f"❌ Request with order ID {order_id} not found.")
        return
        
    request_data = requests[order_id]
    
    if not current_channel:
        await event.reply("❌ No channel set. Use /setchannel first.")
        return
        
    if not contacts:
        await event.reply("❌ No contacts imported. Use /upload_vcf first.")
        return
        
    await event.reply(f"🔄 Starting to add members for order {order_id}...")
    
    target_count = min(request_data.get('members_requested', 0), len(contacts))
    added_count = 0
    failed_count = 0
    
    # Process in batches
    batch_size = 10
    for i in range(0, target_count, batch_size):
        batch = contacts[i:min(i+batch_size, target_count)]
        
        try:
            # Import contacts
            input_users = []
            for contact in batch:
                input_users.append(InputPhoneContact(
                    client_id=random.randint(1, 99999999), 
                    phone=contact['phone'], 
                    first_name=contact['name'][:25],  # Limit name length
                    last_name=""
                ))
            
            # Import contacts
            import_result = await client(functions.contacts.ImportContactsRequest(input_users))
            
            # Prepare users to invite
            users_to_invite = []
            for user in import_result.users:
                if isinstance(user, types.User) and not user.bot:
                    users_to_invite.append(InputUser(user_id=user.id, access_hash=user.access_hash))
            
            # Invite users to channel
            if users_to_invite:
                try:
                    await client(functions.channels.InviteToChannelRequest(
                        channel=current_channel, 
                        users=users_to_invite
                    ))
                    added_count += len(users_to_invite)
                    await event.reply(f"✅ Added {len(users_to_invite)} members (Total: {added_count}/{target_count})")
                except FloodWaitError as e:
                    wait_time = e.seconds
                    await event.reply(f"⏳ Flood wait: Waiting {wait_time} seconds before continuing...")
                    await asyncio.sleep(wait_time)
                    # Retry the same batch
                    i -= batch_size
                except UserPrivacyRestrictedError:
                    await event.reply("⚠️ Some users have privacy restrictions and couldn't be added.")
                    failed_count += len(users_to_invite)
                except Exception as e:
                    logger.error("Error inviting users: %s", e)
                    failed_count += len(users_to_invite)
            
            # Delay between batches to avoid flooding
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error("Error processing batch: %s", e)
            failed_count += len(batch)
            await event.reply(f"❌ Error processing batch: {e}")
    
    # Update request status
    requests[order_id]['status'] = 'completed'
    requests[order_id]['completed_at'] = datetime.now().isoformat()
    requests[order_id]['added_count'] = added_count
    requests[order_id]['failed_count'] = failed_count
    save_data(contacts, requests)
    
    await event.reply(
        f"✅ Order {order_id} completed!\n"
        f"• Successfully added: {added_count} members\n"
        f"• Failed to add: {failed_count} members"
    )

async def handle_status(event):
    status_msg = (
        f"🤖 Userbot Status:\n"
        f"• Phone: {PHONE}\n"
        f"• Contacts loaded: {len(contacts)}\n"
        f"• Current channel: {getattr(current_channel, 'title', 'None')}\n"
        f"• Pending requests: {sum(1 for r in requests.values() if r.get('status') == 'pending')}\n"
    )
    await event.reply(status_msg)

async def handle_help(event):
    help_text = (
        "🤖 Available Commands:\n\n"
        "/upload_vcf - Upload a VCF contact file\n"
        "/setchannel @channel - Set target channel\n"
        "/listcontacts - Show imported contacts\n"
        "/listrequests - Show pending requests\n"
        "/process ORDER_ID - Process a specific order\n"
        "/status - Show userbot status\n"
        "/help - Show this help message"
    )
    await event.reply(help_text)

# Main message handler
@client.on(events.NewMessage)
async def message_handler(event):
    # Ignore messages from channels and bots
    try:
        # Check if sender is a bot
        is_bot = False
        if isinstance(event.sender, User):
            is_bot = event.sender.bot
        elif isinstance(event.sender, Channel):
            # Channels can't send commands, so we can ignore them
            return
            
        if is_bot or event.is_channel:
            return
    except Exception as e:
        logger.error(f"Error checking sender type: {e}")
        return
        
    text = event.raw_text
    
    # Handle commands
    if text.startswith('/'):
        if text.startswith('/upload_vcf'):
            await handle_upload_vcf(event)
        elif text.startswith('/setchannel'):
            await handle_set_channel(event)
        elif text.startswith('/listcontacts'):
            await handle_list_contacts(event)
        elif text.startswith('/listrequests'):
            await handle_list_requests(event)
        elif text.startswith('/process'):
            await handle_process_request(event)
        elif text.startswith('/status'):
            await handle_status(event)
        elif text.startswith('/help'):
            await handle_help(event)
        else:
            await event.reply("Unknown command. Use /help to see available commands.")
    else:
        # Check if this is a VCF file upload
        if event.sender_id in vcf_upload_sessions and event.document:
            await handle_vcf_file(event)

# Start the client
async def main():
    await client.start(phone=PHONE)
    logger.info("Userbot started for %s", PHONE)
    
    # Set up event handler for requests channel
    @client.on(events.NewMessage(chats=requests_channel))
    async def on_request(event):
        text = event.raw_text
        logger.info("Received request:\n%s", text)
        
        # Parse the request
        request_data = parse_request(text)
        if not request_data:
            logger.warning("Could not parse request: %s", text)
            return
            
        # Store the request
        order_id = request_data.get('order_id')
        if order_id:
            requests[order_id] = {
                **request_data,
                'received_at': datetime.now().isoformat(),
                'status': 'pending'
            }
            save_data(contacts, requests)
            logger.info("Stored request with order ID: %s", order_id)
            
            # Notify about new request
            await event.reply(f"✅ Request received and stored (Order ID: {order_id}). Use /process {order_id} to start.")

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
