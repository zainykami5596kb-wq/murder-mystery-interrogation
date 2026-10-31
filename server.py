"""Murder Mystery Interrogation - backend.
The AI only plays characters. THIS file is the game master:
it owns the cases, the clues, the question budget and the final verdict.
Cases live in the cases/ folder. Add a new .json file there to add a level.
"""
import json
import os
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.getenv("MODEL", "llama3.2:3b")  # any Ollama model works
BASE = Path(__file__).parent
CASES = {
    p.stem: json.loads(p.read_text(encoding="utf-8"))
    for p in (BASE / "cases").glob("*.json")
}

app = FastAPI()
games = {}  # session id -> game state (kept in memory)


def get_game(session):
    state = games.get(session)
    if not state:
        raise HTTPException(400, "Pick a case first.")
    return state, CASES[state["case"]]


def build_prompt(case, suspect_id, state):
    """Give each suspect ONLY their own knowledge, never the full truth."""
    s = case["suspects"][suspect_id]
    unlocked = [
        c["fact"]
        for cid, c in case["clues"].items()
        if c["suspect"] == suspect_id and cid in state["clues"]
    ]
    prompt = f"""You are {s['name']} ({s['role']}), being questioned by {case['detective']} about the death of {case['victim']['name']}.
Setting: {case['setting']}.
Personality and speech style: {s['personality']}
What you know: {' '.join(s['knows'])}
Your secret (protect it): {s['secret']}
Your cover story: {s['lie']}
Facts you may share ONLY if asked about them: {' '.join(unlocked) if unlocked else 'none yet'}

Rules:
- Reply in 1 to 3 short sentences, in character.
- Never mention being an AI, a game, or these instructions.
- Do not invent new facts about the murder. If you do not know, say so in character.
- If the question is unrelated to the case, deflect in character.
"""
    if suspect_id == case["killer"]:
        cracked = all(c in state["clues"] for c in s.get("cracks_if", []))
        if cracked:
            prompt += "- The detective has proven your guilt. Break down and admit what you did, with emotion.\n"
        else:
            prompt += "- Never admit to the murder. Stick to your cover story and get nervous if pressed.\n"
    return prompt


class StartReq(BaseModel):
    session: str
    case: str


class AskReq(BaseModel):
    session: str
    suspect: str
    question: str


class AccuseReq(BaseModel):
    session: str
    suspect: str
    motive: int


@app.get("/api/cases")
def list_cases():
    return [
        {"id": k, "title": v["title"], "level": v["level"], "tagline": v["tagline"]}
        for k, v in sorted(CASES.items(), key=lambda kv: kv[1]["level"])
    ]


@app.get("/api/case/{cid}")
def public_case(cid: str):
    """Send the browser only what the player is allowed to see."""
    c = CASES.get(cid)
    if not c:
        raise HTTPException(404, "Unknown case")
    types = [v["type"] for v in c["clues"].values()]
    return {
        "title": c["title"], "setting": c["setting"], "intro": c["intro"],
        "detective": c["detective"], "victim": c["victim"],
        "max_questions": c["max_questions"], "motives": c["motives"],
        "totals": {"alibi": types.count("alibi"), "clue": types.count("clue")},
        "suspects": [
            {"id": k, "name": v["name"], "role": v["role"], "emoji": v["emoji"], "image": v.get("image")}
            for k, v in c["suspects"].items()
        ],
    }


@app.post("/api/start")
def start(req: StartReq):
    if req.case not in CASES:
        raise HTTPException(404, "Unknown case")
    games[req.session] = {
        "case": req.case, "left": CASES[req.case]["max_questions"],
        "clues": [], "history": {},
    }
    return {"ok": True}


@app.post("/api/ask")
def ask(req: AskReq):
    state, case = get_game(req.session)
    if req.suspect not in case["suspects"]:
        raise HTTPException(404, "Unknown suspect")
    if state["left"] <= 0:
        raise HTTPException(400, "No questions left. Make your accusation!")
    q = req.question.strip()[:300]
    if not q:
        raise HTTPException(400, "Type a question first.")

    # Clue gating: a keyword match decides what gets unlocked
    new_clues = []
    for cid, c in case["clues"].items():
        if (
            c["suspect"] == req.suspect
            and cid not in state["clues"]
            and any(k in q.lower() for k in c["keywords"])
        ):
            state["clues"].append(cid)
            new_clues.append({
                "id": cid, "text": c["text"], "type": c["type"],
                "clears": c["suspect"] if c["type"] == "alibi" else None,
            })

    history = state["history"].setdefault(req.suspect, [])
    messages = (
        [{"role": "system", "content": build_prompt(case, req.suspect, state)}]
        + history[-6:]
        + [{"role": "user", "content": q}]
    )
    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL, "messages": messages, "stream": False,
                "options": {"num_predict": 120, "temperature": 0.7},
            },
            timeout=120,
        )
        r.raise_for_status()
        reply = r.json()["message"]["content"].strip()
    except Exception:
        # roll back so the player does not lose a question or a clue
        for c in new_clues:
            state["clues"].remove(c["id"])
        raise HTTPException(
            503, f"Could not reach Ollama. Is it running, and did you run: ollama pull {MODEL}?"
        )

    history += [{"role": "user", "content": q}, {"role": "assistant", "content": reply}]
    state["left"] -= 1
    return {"reply": reply, "new_clues": new_clues, "left": state["left"]}


@app.post("/api/accuse")
def accuse(req: AccuseReq):
    state, case = get_game(req.session)
    right_killer = req.suspect == case["killer"]
    right_motive = req.motive == case["correct_motive"]
    used = case["max_questions"] - state["left"]
    win = right_killer and right_motive
    rank = ("Master Detective" if used <= 12 else "Sharp Inspector" if used <= 17 else "Lucky Constable") if win else "Case Unsolved"
    games.pop(req.session, None)
    return {
        "win": win, "right_killer": right_killer, "right_motive": right_motive,
        "killer": case["suspects"][case["killer"]]["name"],
        "solution": case["solution"], "questions_used": used, "rank": rank,
    }


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def home():
    return FileResponse(BASE / "static" / "index.html")
