"""Titans Told voice-account picker (owner decisions 12 Nov 2026, third account 14 Nov 2026). Never prints keys.
usage: tt_quota.py --job CHARS [--bmp-regular N --bmp-roundups N] [--tt-pro-used N]
Reads all three ElevenLabs accounts and prints their quotas, then the ONE account to use for one whole video:
  1. Second account (ELEVENLABS_API_KEY_2): Titans Told may use all of it -> if left >= job.
  2. Third account (ELEVENLABS_API_KEY_3): all but the last 25,000 characters (BMP's spare) -> if left - job >= 25,000.
  3. Main Pro (ELEVENLABS_API_KEY): at most 115,000 Titans Told characters per Pro cycle (pass --tt-pro-used from the
     voice log), and never below BMP's reserve: reserve = 13,000 x BMP regular videos left + 22,000 x BMP round-ups
     left + 1,050 x days to the Pro reset (Off-Road Handbook), counts from the Drive doc "TT – BMP voice reserve".
  4. Else NONE (pause the video and email the owner).
Exit code 0 = an account was chosen (printed as USE=<env var>), 3 = none. --job 0 just prints the quotas."""
import argparse, json, os, sys, time, urllib.request
ap = argparse.ArgumentParser()
ap.add_argument("--job", type=int, required=True)
ap.add_argument("--bmp-regular", type=int, default=None)
ap.add_argument("--bmp-roundups", type=int, default=None)
ap.add_argument("--tt-pro-used", type=int, default=0, help="Titans Told characters already used on Pro this Pro cycle")
ap.add_argument("--tt-pro-cap", type=int, default=115000)
ap.add_argument("--third-spare", type=int, default=25000)
a = ap.parse_args()
acc = {}
for var, label in (("ELEVENLABS_API_KEY_2", "second"), ("ELEVENLABS_API_KEY_3", "third"), ("ELEVENLABS_API_KEY", "pro")):
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
    acc[label] = dict(var=var, left=left, days=round(days, 1))
    reset = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(d["next_character_count_reset_unix"]))
    print(f"{label} ({d.get('tier')}): used {d['character_count']:,}, left {left:,} of {d['character_limit']:,}, resets {reset} ({days:.1f} days)")
tt_room = sum([acc["second"]["left"] if "second" in acc else 0, max(0, acc["third"]["left"] - a.third_spare) if "third" in acc else 0,
               max(0, a.tt_pro_cap - a.tt_pro_used) if "pro" in acc else 0])
print(f"total left on all accounts: {sum(x['left'] for x in acc.values()):,} | Titans Told room (second + third above spare + Pro share, before BMP reserve): {tt_room:,}")
if a.job <= 0:
    sys.exit(0)
s = acc.get("second")
if s and s["left"] >= a.job:
    print(f"USE={s['var']} (second account first)"); sys.exit(0)
t = acc.get("third")
if t:
    print(f"third: after this job {t['left'] - a.job:,} left (must stay >= {a.third_spare:,} for BMP)")
    if t["left"] - a.job >= a.third_spare:
        print(f"USE={t['var']} (third account)"); sys.exit(0)
p = acc.get("pro")
if p:
    if a.bmp_regular is None or a.bmp_roundups is None:
        print("pro: BMP counts not given, so Pro is not used"); print("USE=NONE"); sys.exit(3)
    reserve = 13000 * a.bmp_regular + 22000 * a.bmp_roundups + int(1050 * p["days"])
    room_cap = a.tt_pro_cap - a.tt_pro_used
    print(f"pro: BMP reserve {reserve:,}; after this job Pro would have {p['left'] - a.job:,}; TT Pro share room {room_cap:,} of {a.tt_pro_cap:,}")
    if p["left"] - a.job >= reserve and a.job <= room_cap:
        print(f"USE={p['var']} (main Pro, within Titans Told's share)"); sys.exit(0)
print("USE=NONE"); sys.exit(3)
