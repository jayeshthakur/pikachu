#!/usr/bin/env python3
"""
Daily Pikachu content pipeline.

Pulls fresh, non-repeating Pikachu facts (habits, powers) from PokeAPI and
fresh Pikachu news from DuckDuckGo News, writes one markdown file per
category per day under content/{habits,powers,daily_news}, and tracks what
has already been used so nothing repeats within a 7-day cycle. Every 7 days
the content directories are purged and a new cycle starts.

News URLs are deduplicated forever (never purged) so the same article is
never reposted even across cycles.
"""
import json
import random
import sys
from datetime import date, datetime
from hashlib import sha1
from pathlib import Path

import requests
from ddgs import DDGS

BASE_DIR = Path(__file__).resolve().parent.parent
CONTENT_DIR = BASE_DIR / "content"
STATE_FILE = BASE_DIR / "state" / "state.json"
CATEGORIES = ["habits", "powers", "daily_news"]
CYCLE_DAYS = 7
POKEAPI = "https://pokeapi.co/api/v2"
REQUEST_TIMEOUT = 20


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "cycle_start": None,
        "cycle_seen_flavor_ids": [],
        "cycle_seen_moves": [],
        "cycle_seen_abilities": [],
        "news_seen_urls": [],
    }


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def purge_if_cycle_expired(state: dict) -> dict:
    today = date.today()
    cycle_start = (
        date.fromisoformat(state["cycle_start"]) if state.get("cycle_start") else None
    )
    if cycle_start is None or (today - cycle_start).days >= CYCLE_DAYS:
        log(f"Cycle expired (start={cycle_start}) — purging content and starting a new cycle.")
        for cat in CATEGORIES:
            cat_dir = CONTENT_DIR / cat
            cat_dir.mkdir(parents=True, exist_ok=True)
            for f in cat_dir.glob("*.md"):
                f.unlink()
        state["cycle_start"] = today.isoformat()
        state["cycle_seen_flavor_ids"] = []
        state["cycle_seen_moves"] = []
        state["cycle_seen_abilities"] = []
        # news_seen_urls is intentionally NOT reset — news must never repeat, ever.
    return state


def fetch_habits(state: dict, today: date) -> None:
    """Pikadex flavor-text entries (behavior/habitat descriptions), unique per cycle."""
    r = requests.get(f"{POKEAPI}/pokemon-species/pikachu", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    species = r.json()

    entries = [
        e for e in species["flavor_text_entries"] if e["language"]["name"] == "en"
    ]
    seen = set(state["cycle_seen_flavor_ids"])
    unseen = []
    for e in entries:
        text = " ".join(e["flavor_text"].split())
        uid = f"{e['version']['name']}:{sha1(text.encode()).hexdigest()[:10]}"
        if uid not in seen:
            unseen.append((uid, e["version"]["name"], text))

    if not unseen:
        log("habits: no unseen Pokedex entries left this cycle, skipping today's file.")
        return

    picks = random.sample(unseen, k=min(3, len(unseen)))
    lines = [f"# Pikachu Habits & Behavior — {today.isoformat()}\n"]
    lines.append(f"Source: [PokeAPI](https://pokeapi.co/api/v2/pokemon-species/pikachu)\n")
    for uid, version, text in picks:
        state["cycle_seen_flavor_ids"].append(uid)
        lines.append(f"## Pokédex entry ({version})\n\n{text}\n")

    habitat = species.get("habitat")
    lines.append(f"\n---\nHabitat: {habitat['name'] if habitat else 'unknown'}  ")
    lines.append(f"Capture rate: {species.get('capture_rate')}  ")
    lines.append(f"Egg groups: {', '.join(g['name'] for g in species.get('egg_groups', []))}\n")

    out = CONTENT_DIR / "habits" / f"{today.isoformat()}.md"
    out.write_text("\n".join(lines))
    log(f"habits: wrote {out} ({len(picks)} new entries)")


def fetch_powers(state: dict, today: date) -> None:
    """Abilities (once per cycle) + a rotating batch of unique moves."""
    r = requests.get(f"{POKEAPI}/pokemon/pikachu", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    pokemon = r.json()

    lines = [f"# Pikachu Powers & Abilities — {today.isoformat()}\n"]
    lines.append(f"Source: [PokeAPI](https://pokeapi.co/api/v2/pokemon/pikachu)\n")

    seen_abilities = set(state["cycle_seen_abilities"])
    new_abilities = [
        a["ability"]["name"] for a in pokemon["abilities"] if a["ability"]["name"] not in seen_abilities
    ]
    if new_abilities:
        lines.append("## Abilities\n")
        for name in new_abilities:
            ar = requests.get(f"{POKEAPI}/ability/{name}", timeout=REQUEST_TIMEOUT)
            ar.raise_for_status()
            ability = ar.json()
            effect = next(
                (e["effect"] for e in ability["effect_entries"] if e["language"]["name"] == "en"),
                "No description available.",
            )
            lines.append(f"### {name.replace('-', ' ').title()}\n\n{' '.join(effect.split())}\n")
            state["cycle_seen_abilities"].append(name)

    seen_moves = set(state["cycle_seen_moves"])
    all_moves = [m["move"]["name"] for m in pokemon["moves"]]
    unseen_moves = [m for m in all_moves if m not in seen_moves]

    if unseen_moves:
        picks = random.sample(unseen_moves, k=min(5, len(unseen_moves)))
        lines.append("## Moves\n")
        for name in picks:
            mr = requests.get(f"{POKEAPI}/move/{name}", timeout=REQUEST_TIMEOUT)
            mr.raise_for_status()
            move = mr.json()
            effect = next(
                (e["short_effect"] for e in move["effect_entries"] if e["language"]["name"] == "en"),
                "",
            )
            lines.append(
                f"### {name.replace('-', ' ').title()}\n\n"
                f"Type: {move['type']['name']} | Power: {move.get('power')} | "
                f"Accuracy: {move.get('accuracy')} | PP: {move.get('pp')} | "
                f"Class: {move['damage_class']['name']}\n\n{' '.join(effect.split())}\n"
            )
            state["cycle_seen_moves"].append(name)
    else:
        log("powers: no unseen moves left this cycle.")

    if not new_abilities and not unseen_moves:
        log("powers: nothing new this cycle, skipping today's file.")
        return

    moves_written = len(picks) if unseen_moves else 0
    out = CONTENT_DIR / "powers" / f"{today.isoformat()}.md"
    out.write_text("\n".join(lines))
    log(f"powers: wrote {out} ({len(new_abilities)} abilities, {moves_written} moves)")


def fetch_daily_news(state: dict, today: date) -> None:
    """Fresh Pikachu/Pokemon news via DuckDuckGo, never repeating a URL."""
    seen_urls = set(state["news_seen_urls"])
    results = []
    try:
        with DDGS() as ddgs:
            results = list(
                ddgs.news("Pikachu", region="wt-wt", safesearch="moderate", timelimit="w", max_results=20)
            )
    except Exception as exc:  # network / rate-limit hiccups shouldn't kill the run
        log(f"daily_news: search failed: {exc}")

    def relevance(item):
        blob = f"{item.get('title', '')} {item.get('body', '')}".lower()
        has_pikachu = "pikachu" in blob
        has_pokemon = "pokemon" in blob or "pokémon" in blob
        if has_pikachu and has_pokemon:
            return 0
        if has_pikachu:
            return 1
        return 2

    results = [r for r in results if relevance(r) <= 1]  # must at least mention Pikachu
    results.sort(key=relevance)

    picks = []
    for item in results:
        url = item.get("url")
        if not url or url in seen_urls:
            continue
        picks.append(item)
        seen_urls.add(url)
        if len(picks) >= 5:
            break

    if not picks:
        log("daily_news: no new articles found today.")
        out = CONTENT_DIR / "daily_news" / f"{today.isoformat()}.md"
        out.write_text(f"# Pikachu News — {today.isoformat()}\n\nNo new articles found today.\n")
        return

    lines = [f"# Pikachu News — {today.isoformat()}\n"]
    for item in picks:
        lines.append(f"## {item.get('title')}\n")
        lines.append(f"- Date: {item.get('date', 'unknown')}")
        lines.append(f"- Source: {item.get('source', 'unknown')}")
        lines.append(f"- URL: {item.get('url')}\n")
        if item.get("body"):
            lines.append(f"{item['body']}\n")
        state["news_seen_urls"].append(item["url"])

    out = CONTENT_DIR / "daily_news" / f"{today.isoformat()}.md"
    out.write_text("\n".join(lines))
    log(f"daily_news: wrote {out} ({len(picks)} new articles)")

    # keep the dedup list from growing forever
    state["news_seen_urls"] = state["news_seen_urls"][-1000:]


def main() -> int:
    for cat in CATEGORIES:
        (CONTENT_DIR / cat).mkdir(parents=True, exist_ok=True)

    state = load_state()
    state = purge_if_cycle_expired(state)
    today = date.today()

    ok = True
    for fn, name in (
        (fetch_habits, "habits"),
        (fetch_powers, "powers"),
        (fetch_daily_news, "daily_news"),
    ):
        try:
            fn(state, today)
        except Exception as exc:
            ok = False
            log(f"{name}: FAILED — {exc}")

    save_state(state)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
