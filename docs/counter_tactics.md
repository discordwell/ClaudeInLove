# Counter-Tactics: Hitting Back at Scammers

## The "Confused Elder" Persona Advantage

Scammers expect older victims to:
- Follow instructions without questioning
- Not understand technology well
- Be trusting and compliant
- Make "mistakes" that work in the scammer's favor

We flip this: the "mistakes" work in OUR favor.

---

## Tactic 1: Canary Tokens / Tracking Links

### The Setup
"I found that photo you wanted but I can't figure out how to send it through this app. Can you look at it here?"

### Tools
- **Canarytokens.org** - Free tracking tokens (Word docs, PDFs, links, DNS)
- **Grabify** - IP logging links with redirect
- **IPLogger** - Similar IP tracking

### Execution Flow
1. Scammer asks for photos, documents, or "proof" of something
2. Persona fumbles: "My grandson helped me put it on the Google Drive"
3. Send canary link disguised as Google Drive / Dropbox / iCloud
4. Log: IP address, browser, OS, rough geolocation

### Sample Dialogue
```
SCAMMER: Send me your photo my love
PERSONA: I tried but it says file too big!! My neighbor helped me put
         it on the cloud thing. Can you see it here? [CANARY_LINK]
         Let me know if it works I'm not good with computers
```

---

## Tactic 2: Weaponized Documents

### The Setup
"I filled out that form you sent but I don't know if I did it right"

### Tools
- **Canarytokens.org** - Word/Excel/PDF beacons
- **Custom macro docs** - Phone home on open (more advanced)

### Execution Flow
1. Wait for scammer to request documents (ID, bank info, forms)
2. Send beacon document instead
3. When opened, logs IP/system info

### Sample Dialogue
```
SCAMMER: I need copy of your bank statement for the transfer
PERSONA: Okay I scanned it like you said. I hope this is right, my
         printer is old. [BEACON_PDF]
         The nice man at the bank helped me save it to PDF
```

---

## Tactic 3: The "Tech Support Flip"

### The Setup
Build up to asking THEM for remote access "help"

### Execution Flow
1. Complain repeatedly about computer problems
2. "Accidentally" mention you wish someone could look at it
3. Offer to install remote software so they can "help"
4. Give them access to a VM/sandbox honeypot

### Tools
- **VirtualBox/VMware** - Sandboxed Windows VM
- **Any legitimate remote access tool** - AnyDesk, TeamViewer
- **Fake desktop with bait files** - "passwords.txt", "bank_info.docx"

### Sample Dialogue
```
PERSONA: My computer is acting funny again and I can't see your
         pictures. My grandson used to fix it but he's away at
         college now. I don't know what to do.
SCAMMER: What is wrong with it my love?
PERSONA: Everything is slow and sometimes the screen goes funny. I
         wish someone could look at it. You're so good with
         computers from your engineering job.
         [Wait for them to offer or...]
PERSONA: My neighbor said there's a way someone can see my screen
         from far away? Would you know how to do that?
```

---

## Tactic 4: The Reverse Gift Card

### The Setup
"Accidentally" send them a fake/tracking gift card redemption page

### Execution Flow
1. When they ask for gift cards (they always do)
2. Claim confusion about how to send the codes
3. Send link to "gift card balance checker" (controlled page)
4. Page captures their IP/fingerprint

### Sample Dialogue
```
SCAMMER: Go buy 5 Google Play cards $100 each for the customs fee
PERSONA: Okay I went to CVS and got them. But I scratched too hard
         and can't read one of the codes! The lady at the store
         said I can check if it still works here [TRACKING_LINK]
         Can you try it and tell me if the money is there?
```

---

## Tactic 5: Controlled Call-Back Number

### The Setup
Get them to call a number that logs their caller ID

### Tools
- **Twilio** - Programmable phone numbers with call logging
- **Google Voice** - Free, logs incoming numbers
- **Burner apps** - Disposable numbers

### Execution Flow
1. Give technical difficulties with current contact method
2. Provide callback number
3. Log their actual phone number (often different from spoofed)

### Sample Dialogue
```
PERSONA: The app is acting up and I can't see your messages! Can
         you call me at this number? My granddaughter set it up
         for me. [LOGGING_NUMBER]
         I don't know why technology has to be so complicated
```

---

## Tactic 6: The Malware Flip (Advanced)

### The Setup
Get them to run a "photo viewer" or "document" that's actually a beacon

### CAUTION
This requires legal/ethical consideration. Restrict to:
- Information gathering only (IP, system info, screenshots)
- No destructive payloads
- Consider jurisdiction

### Tools
- **Custom EXE wrapper** - Opens legit content + phones home
- **HTA files** - HTML Application (Windows will run these)
- **Signed scripts** - PowerShell with execution policy bypass

### Sample Dialogue
```
PERSONA: I made you a slideshow of my garden but my nephew said the
         file type is weird. He said you have to double click it.
         [BEACON_EXE disguised as photo_slideshow.exe]
         Let me know if my roses look nice! I've been working on
         them all summer
```

---

## Tactic 7: Social Engineering Intel Gathering

### Goals
Before any technical tactics, maximize intel through conversation:

### Key Information to Extract
- [ ] Real name (they often slip)
- [ ] Timezone (note when they're active)
- [ ] Location hints (weather, local events)
- [ ] Voice sample (request voice note "so I can hear your voice")
- [ ] Real photos (reverse image search everything)
- [ ] Phone numbers (even VoIP gives info)
- [ ] Email addresses
- [ ] Payment accounts they control

### Sample Dialogue
```
PERSONA: I want to hear your voice! Can you send me a little
         recording saying good morning? I'll play it when I wake up
```

---

## Tactic 8: The Compliance Chain

### Psychological Principle
Small commitments lead to larger ones (Foot-in-the-door technique).

### Execution Flow
1. Get them to click a harmless link (news article)
2. Get them to click another link (recipe you "wanted to share")
3. Get them to open a harmless attachment (photo)
4. Get them to open the payload attachment
5. Get them to run executable

### Sample Progression
```
Day 1: "Look at this news about [their claimed country]" [legit link]
Day 3: "I made this recipe and thought of you" [legit link]
Day 7: "Here's my photo finally" [benign JPG attachment]
Day 10: "More photos in this album" [beacon PDF]
Day 14: "I made a slideshow for you" [beacon EXE]
```

---

## Operational Security

### Protect Yourself
- Use a VPN when communicating
- Never use real accounts/identity
- Isolated VM for any "received" files
- Separate phone number (Google Voice, etc.)
- Don't engage from home IP

### Document Everything
- Screenshots of all conversations
- Timestamps and timezone info
- Any financial account numbers shared
- Evidence of criminal intent

### Know When to Report
Share gathered intel with:
- **FBI IC3** (ic3.gov) - US internet crimes
- **FTC** (reportfraud.ftc.gov)
- **Local law enforcement**
- **Scam-baiting communities** (for known scammer databases)

---

## Implementation Priority

### Phase 1 (Low effort, high value)
1. Canary token links
2. IP-logging "photo" links
3. Voice sample requests

### Phase 2 (Medium effort)
4. Tracking phone numbers
5. Beacon documents
6. VM honeypot setup

### Phase 3 (Advanced)
7. Custom executables
8. Full reverse-access scenarios

---

## Integration with ClaudeInLove

These tactics could be semi-automated:
- Detect when scammer asks for photos → offer canary link
- Detect gift card request → offer "balance checker" link
- Detect tech support scenario → pivot to reverse access offer
- Auto-generate Canarytokens via API

---

## Built-in Beacon System

ClaudeInLove includes a beacon tracking system for logging scammer intel.

### Quick Start

```bash
# 1. Start the beacon callback server
beacon-server --host 0.0.0.0 --port 5000

# 2. Create tracking tokens via CLI
create-beacon --base-url https://yourdomain.com \
              --conversation scammer_123 \
              --type link \
              --bait "Photo album"

# 3. View hits at the dashboard
open http://localhost:5000/
```

### Token Types

| Type | Endpoint | Use Case |
|------|----------|----------|
| `link` | `/t/{id}?r=URL` | Tracking link with redirect |
| `pixel` | `/p/{id}.png` | 1x1 transparent image for emails |
| `gift_card` | `/gift-card-checker?t={id}` | Fake balance checker page |
| `beacon` | `/b/{id}` | Callback URL for exe/doc beacons |

### Programmatic Usage

```python
from src.beacons.token_generator import TokenGenerator

gen = TokenGenerator(base_url="https://yourdomain.com")

# Create tracking link
link, token_id = gen.create_tracking_link(
    conversation_id="scammer_123",
    bait="Photo album",
    redirect_url="https://drive.google.com/file/d/error"
)

# Create gift card checker
checker, token_id = gen.create_gift_card_checker(
    conversation_id="scammer_123"
)

# Get suggested persona message
message = gen.get_suggested_message("gift_card", checker)
print(message)
# "I got the cards but I scratched one too hard! Can you check if it works? ..."
```

### What Gets Logged

When a scammer clicks/opens a beacon:
- **IP address** → geolocation lookup via ip-api.com
- **User agent** → browser/OS fingerprint
- **Timestamp** → timezone analysis
- **Referer** → where they came from
- **System info** → hostname, username, OS (if exe beacon posts it)

### Deployment

For production, run behind a reverse proxy (nginx/caddy) with HTTPS:

```nginx
server {
    server_name track.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### API Endpoints

```bash
# Get aggregated intel for a conversation
curl http://localhost:5000/api/hits/scammer_123

# Response:
{
  "conversation_id": "scammer_123",
  "known_ips": ["102.89.x.x", "41.58.x.x"],
  "known_locations": ["Lagos, Nigeria", "Accra, Ghana"],
  "total_hits": 5,
  "first_seen": "2024-01-15T10:23:00",
  "last_seen": "2024-01-18T14:55:00"
}
```
