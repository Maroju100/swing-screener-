"""Command line for the guest-message agent.

  python -m guest_agent handle --property examples/vegas_condo.json --booking examples/booking.json \
      --message "What's the wifi password?"
  python -m guest_agent queue
  python -m guest_agent approve 3 [--text "edited reply"]
  python -m guest_agent reject 3

`handle` never sends anywhere real: the Sender below prints. Swap in a channel adapter
(Hostaway / Guesty / Airbnb messaging API) once a client signs up.
"""
import argparse
import json
import sys

from .agent import Booking, decide
from .queue import Queue


class ConsoleSender:
    def send(self, guest, text):
        print(f"\n--> SENT to {guest}:\n{text}\n")


def notify_on_call(prop, item_id, message):
    who = prop.get("on_call", {}).get("name", "the host")
    print(f"\n!!! EMERGENCY (item {item_id}) - page {who} now: {message}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="guest_agent")
    ap.add_argument("--db", default="guest_agent.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("handle")
    h.add_argument("--property", required=True)
    h.add_argument("--booking", required=True)
    h.add_argument("--message", required=True)
    h.add_argument("--dry-run", action="store_true", help="queue everything, send nothing")
    sub.add_parser("queue")
    a = sub.add_parser("approve"); a.add_argument("id", type=int); a.add_argument("--text")
    r = sub.add_parser("reject"); r.add_argument("id", type=int)
    args = ap.parse_args(argv)
    q = Queue(args.db)

    if args.cmd == "handle":
        import anthropic
        prop = json.load(open(args.property))
        booking = Booking(**json.load(open(args.booking)))
        d = decide(anthropic.Anthropic(), prop, booking, [], args.message)
        send_now = d.route == "auto_send" and not args.dry_run and prop.get("rules", {}).get("auto_send", False)
        item = q.record(prop["id"], booking.guest_name, args.message, d, sent=send_now)
        print(json.dumps({"item": item, **d.to_dict(), "reply": "(hidden)" if d.reply != d.draft else d.reply},
                         indent=1))
        if send_now:
            ConsoleSender().send(booking.guest_name, d.reply)
        elif d.route == "emergency":
            notify_on_call(prop, item, args.message)
        else:
            print(f"\nQueued for approval as item {item}. Draft:\n{d.draft}\n")
    elif args.cmd == "queue":
        for it in q.pending():
            print(f"[{it['id']}] {it['status'].upper():9} {it['guest']}: {it['message']}")
            print(f"     draft: {it['draft']}")
            print(f"     why:   {', '.join(json.loads(it['reasons']))}\n")
    elif args.cmd == "approve":
        it = q.get(args.id)
        text = args.text or it["reply"]
        if "{{" in text:
            print("draft still holds a placeholder (code not released); approve with --text instead")
            return 1
        q.decide(args.id, "sent", text)
        ConsoleSender().send(it["guest"], text)
    elif args.cmd == "reject":
        q.decide(args.id, "rejected")
        print(f"item {args.id} rejected; nothing sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
