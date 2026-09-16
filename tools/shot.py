#!/usr/bin/env python3
"""Open the board in headless Chromium, print console output, take screenshots.

Usage: shot.py URL OUT_PREFIX [--width 1440] [--height 900] [--wait 6] [--actions hover,zoom,light]
"""
import argparse, json, sys, time
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("url"); ap.add_argument("out")
ap.add_argument("--width", type=int, default=1440); ap.add_argument("--height", type=int, default=900)
ap.add_argument("--wait", type=float, default=6); ap.add_argument("--actions", default="")
ap.add_argument("--exe", default=None)
a = ap.parse_args()

with sync_playwright() as p:
    kw = {"executable_path": a.exe} if a.exe else {}
    b = p.chromium.launch(**kw)
    pg = b.new_page(viewport={"width": a.width, "height": a.height}, device_scale_factor=1)
    logs = []
    pg.on("console", lambda m: logs.append(f"[console.{m.type}] {m.text}"))
    pg.on("pageerror", lambda e: logs.append(f"[pageerror] {e}"))
    pg.on("requestfailed", lambda r: logs.append(f"[requestfailed] {r.url} {r.failure}"))
    t0 = time.time()
    pg.goto(a.url)
    # wait until the page reports idle or timeout
    deadline = t0 + a.wait
    while time.time() < deadline:
        txt = pg.eval_on_selector("#freshText", "e => e.textContent")
        if txt.startswith("updated") or "cannot" in txt or "no event" in txt: break
        time.sleep(0.25)
    time.sleep(0.6)
    fresh = pg.eval_on_selector("#freshText", "e => e.textContent")
    n_cards = pg.evaluate("document.querySelectorAll('.card').length")
    n_runs = pg.evaluate("document.querySelectorAll('#runs li').length")
    print(f"loaded in {time.time()-t0:.1f}s · status='{fresh}' · {n_runs} runs · {n_cards} cards")
    pg.screenshot(path=f"{a.out}.png")
    if n_cards == 0:
        print("no cards; state text:", pg.evaluate("document.querySelector('#content').innerText.slice(0,300)"))
    for act in [x for x in a.actions.split(",") if x and n_cards]:
        if act == "hover":
            card = pg.query_selector(".card .plot")
            box = card.bounding_box()
            pg.mouse.move(box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.5)
            time.sleep(0.3); pg.screenshot(path=f"{a.out}-hover.png")
        elif act == "zoom":
            card = pg.query_selector(".card .plot"); box = card.bounding_box()
            pg.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + 40); pg.mouse.down()
            pg.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + 60, steps=5); pg.mouse.up()
            time.sleep(0.3); pg.screenshot(path=f"{a.out}-zoom.png")
            pg.mouse.dblclick(box["x"] + box["width"] * 0.4, box["y"] + 50)
        elif act == "light":
            pg.click("#themeBtn"); time.sleep(0.4); pg.screenshot(path=f"{a.out}-light.png"); pg.click("#themeBtn")
        elif act == "smooth":
            pg.evaluate("(()=>{const s=document.querySelector('#smooth'); s.value=0.8; s.dispatchEvent(new Event('input'))})()")
            time.sleep(0.4); pg.screenshot(path=f"{a.out}-smooth.png")
        elif act == "log":
            pg.click("#ymode button[data-v=log]"); time.sleep(0.4); pg.screenshot(path=f"{a.out}-log.png"); pg.click("#ymode button[data-v=lin]")
        elif act == "time":
            pg.click("#xmode button[data-v=rel]"); time.sleep(0.4); pg.screenshot(path=f"{a.out}-time.png"); pg.click("#xmode button[data-v=step]")
        elif act == "big":
            pg.hover(".card"); pg.click(".card .big"); time.sleep(0.4); pg.screenshot(path=f"{a.out}-big.png")
        elif act.startswith("tag="):
            pg.fill("#tagFilter", act[4:]); time.sleep(0.5); pg.screenshot(path=f"{a.out}-tag.png")
        elif act.startswith("scroll"):
            pg.evaluate("document.querySelector('#main').scrollTop = 900"); time.sleep(0.5); pg.screenshot(path=f"{a.out}-scroll.png")
    for l in logs: print(l)
    b.close()
