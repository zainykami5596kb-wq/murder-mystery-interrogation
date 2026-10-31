# Murder Mystery Interrogation

A murder mystery game where every suspect is an **open-weight LLM** (Llama 3.2 via Ollama) playing a character. Interrogate four suspects in a rooftop chai dhaba in Islamabad, collect clues, and accuse the killer before you run out of questions.

Built at Hacktoberfest Islamabad.

## How it works
- The AI only plays characters. Our Python code is the game master: it holds the case (`case.json`), unlocks clues when you ask the right questions, limits your questions, and checks your final accusation.
- Each suspect receives only their own knowledge, so they can't spoil the ending.
- Clue gating: a suspect can only reveal a fact after you ask about it. The killer only confesses once you have uncovered all the evidence against them.

## Run it
1. Install [Python 3.10+](https://python.org) and [Ollama](https://ollama.com)
2. `ollama pull llama3.2:3b`
3. `pip install -r requirements.txt`
4. `python -m uvicorn server:app --reload`
5. Open http://localhost:8000

Use another model with `MODEL=qwen2.5:7b python -m uvicorn server:app` (on Windows PowerShell: `$env:MODEL="qwen2.5:7b"` first).

## Files
- `server.py` backend and game logic
- `cases/` one JSON file per level (add a file to add a level)
- `static/index.html` the game UI

## License
MIT
