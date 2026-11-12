"""Titans Told voice-account picker (owner decision 12 Nov 2026). Never prints keys.
usage: tt_quota.py --job CHARS [--bmp-regular N --bmp-roundups N]
Reads both ElevenLabs accounts and prints their quotas, then the account to use for ONE whole video:
  1. Creator (ELEVENLABS_API_KEY_2) first, if left >= job.
  2. Else shared Pro (ELEVENLABS_API_KEY), only if Pro left - job >= BMP reserve, where (until the Pro reset)
     reserve = 13,000 x BMP regular videos left + 22,000 x BMP round-ups left + 1,050 x days to the reset (Off-Road Handbook).
     After a Pro reset, Titans Told's own use of Pro is capped at 250,000 per Pro cycle: pass --tt-pro-used (from the voice log).
  3. Else NONE (pause the video and email the owner).
Exit code 0 = an account was chosen (printed as USE=<env var>), 3 = none."""
import argparse, json, os, sys, time, urllib.request
ap = argparse.ArgumentParser()
ap.add_argument("--job", type=int, required=True)
ap.add_argument("--bmp-regular", type=int, default=None)
ap.add_argument("--bmp-roundups", type=int, default=None)
ap.add_argument("--tt-pro-used", type=int, default=0, help="Titans Told characters already used on Pro this Pro cycle")
ap.add_argument("--tt-pro-cap", type=int, default=250000)
a = ap.parse_args()
acc = {}
for var, label in (("ELEVENLABS_API_KEY_2", "creator"), ("ELEVENLABS_API_KEY", "pro")):
    k = os.environ.get(var)
    if not k:
        print(f"{label}: key {var} not set"); continue
    try:
        r = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": k})
        d = json.load(urllib.request.urlopen(r, timeout=30))
    except Exception as e:
        print(f"{label}: quota check failed ({type(e).__name__})"); continue
    left = d["character_limit"] - d["character_count"]
    days = max(0.0, (d["next_character_count_reset_unix"] - time.time()) / 86400)
    acc[label] = dict(var=var, tier=d.get("tier"), limit=d["character_limit"], used=d["character_count"], left=left,
                      reset=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(d["next_character_count_reset_unix"])), days=round(days, 1))
    print(f"{label} ({d.get('tier')}): left {left:,} of {d['character_limit']:,}, resets {acc[label]['reset']} ({days:.1f} days)")
total = sum(x["left"] for x in acc.values()); print(f"total left: {total:,}")
c = acc.get("creator")
if c and c["left"] >= a.job:
    print(f"USE={c['var']} (creator first)"); sys.exit(0)
p = acc.get("pro")
if p:
    if a.bmp_regular is None or a.bmp_roundups is None:
        print("pro: BMP counts not given, so Pro is not used"); print("USE=NONE"); sys.exit(3)
    reserve = 13000 * a.bmp_regular + 22000 * a.bmp_roundups + int(1050 * p["days"])
    room_cap = a.tt_pro_cap - a.tt_pro_used
    print(f"pro: BMP reserve {reserve:,}; after this job Pro would have {p['left'] - a.job:,}; TT Pro cap room {room_cap:,}")
    if p["left"] - a.job >= reserve and a.job <= room_cap:
        print(f"USE={p['var']} (pro fallback)"); sys.exit(0)
print("USE=NONE"); sys.exit(3)
