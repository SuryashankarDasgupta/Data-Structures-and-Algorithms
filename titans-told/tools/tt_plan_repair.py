# ---- repair pass: move image cuts so every shot is within its limits (exec'd inside plan.py) ----
def T(idx):
    return 0.0 if idx is None else max(0.0, W[idx]["s"] - 0.15)

def lim_of(sc, t0):
    if t0 < 30:
        return (2.05 if t0 > 0 else 0.3), 2.55
    if sc == "IMG":
        return 2.05, 4.35
    typ = sc["type"]
    if typ == "checklist" and "done" in sc:
        return 2.05, 4.4
    return 2.05, GLIM.get(typ, 5.8)

for it in range(80):
    plan.sort(key=lambda x: T(x[0]))
    changed = False
    for k in range(len(plan)):
        a = T(plan[k][0]); b = T(plan[k + 1][0]) if k + 1 < len(plan) else END
        mn, mx = lim_of(plan[k][1], a); d = b - a
        if k + 1 == len(plan):
            mx = max(mx, 12)
        if mn <= d <= mx:
            continue
        if k + 1 < len(plan) and plan[k + 1][1] == "IMG":
            nb = T(plan[k + 2][0]) if k + 2 < len(plan) else END
            cands = [i for i, w in enumerate(W) if a + mn <= w["s"] - 0.15 <= a + mx and 2.05 <= nb - (w["s"] - 0.15) <= (4.35 if w["s"] >= 30 else 2.55)]
            if cands:
                tg = a + (mn + mx) / 2
                j = min(cands, key=lambda i: abs(W[i]["s"] - 0.15 - tg))
                plan[k + 1] = (j, "IMG"); changed = True; break
        if k > 0 and plan[k][1] == "IMG":
            pa = T(plan[k - 1][0]); pmn, pmx = lim_of(plan[k - 1][1], pa)
            cands = [i for i, w in enumerate(W) if pa + pmn <= w["s"] - 0.15 <= pa + pmx and mn <= b - (w["s"] - 0.15) <= mx]
            if cands:
                j = min(cands, key=lambda i: abs(W[i]["s"] - 0.15 - (b - (mn + mx) / 2)))
                plan[k] = (j, "IMG"); changed = True; break
        if d > mx and d >= 2 * mn + 0.1:
            cands = [i for i, w in enumerate(W) if a + mn <= w["s"] - 0.15 <= min(a + mx, b - mn)]
            if cands:
                j = min(cands, key=lambda i: abs(W[i]["s"] - 0.15 - (a + d / 2)))
                plan.append((j, "IMG")); changed = True; break
    if not changed:
        break
plan.sort(key=lambda x: T(x[0]))
bad = []
for k in range(len(plan)):
    a = T(plan[k][0]); b = T(plan[k + 1][0]) if k + 1 < len(plan) else END
    mn, mx = lim_of(plan[k][1], a)
    if k + 1 < len(plan) and not (mn <= b - a <= mx):
        bad.append((round(a, 1), round(b - a, 1), plan[k][1] if plan[k][1] == "IMG" else plan[k][1]["type"]))
print("repair left:", bad)
