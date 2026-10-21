# Guest-message agent (v0.1)

First product from the Automation Studio business plan: drafts replies to short-term-rental
guests from the property's own facts, and only lets safe, routine answers go out on their own.

## How a message is handled

1. **Rules on the guest's words** (`policy.screen_message`): emergency words (gas, leak, locked
   out, injury...) page the on-call person; money, booking changes, complaints, pets, parties
   and off-platform payment go to a human.
2. **Claude drafts** (`agent.draft_reply`): Claude Opus 5.5 at low effort, structured JSON output,
   server-side refusal fallback on. It sees the property facts but **never the real codes** —
   it writes `{{door_code}}` / `{{wifi_password}}` placeholders.
3. **Codes are filled by code, not the model**: only for a verified booking, from 24 hours before
   check-in until checkout. Outside that window the message goes to a human.
4. **Rules on the draft** (`policy.screen_reply`): a draft that offers money, makes a promise,
   contains a link or a long number is held for approval.
5. **The strictest route wins**: `auto_send` < `approval` < `emergency`. Everything is logged in
   SQLite (`guest_agent.db`).

`rules.auto_send` is **false** in the example property: start every new client in
draft-and-approve mode, and switch auto-send on once a few weeks of drafts look right.

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...          # or `ant auth login`
python -m guest_agent handle --property examples/vegas_condo.json \
    --booking examples/booking.json --message "What's the wifi password?"
python -m guest_agent queue            # see what's waiting
python -m guest_agent approve 1        # send as drafted (or --text "edited reply")
python -m guest_agent reject 1
python -m pytest -q                    # 13 routing tests, fake client, no API cost
```

## Not built yet (next steps)

- A channel adapter to read and send real messages (the property-management software the first
  client uses — e.g. Hostaway or Guesty — via its official API). Today `ConsoleSender` prints.
- A small web page for the approval queue (phone-friendly), instead of the command line.
- A test set of 50–100 real guest messages from a pilot client, to measure draft quality before
  turning on auto-send.
- Encrypt the SQLite file or keep codes out of it: approved replies with filled codes are stored.
