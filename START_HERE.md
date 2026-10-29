# START HERE — SpotWise FI with Claude Code + GSD

This kit is everything you need to build **SpotWise FI**: a Finnish electricity price assistant with a data pipeline, an AI agent, an evaluation harness and a small web app. You build it in VS Code with Claude Code, using the GSD ("Get Shit Done") workflow so the work stays planned and doesn't drift.

Read this file once from top to bottom before you start. It takes 10 minutes and saves days.

---

## What's in this kit

| File | What it's for |
|---|---|
| `START_HERE.md` | This guide: setup, the exact commands, in order |
| `CLAUDE.md` | Rules Claude Code reads automatically in every session (stack, style, what not to do) |
| `docs/PROJECT_BRIEF.md` | The full spec: vision, architecture, data model, requirements with IDs, 8-phase roadmap |
| `docs/PHASE_GUIDE.md` | For each phase: what to tell Claude in `discuss-phase`, what "done" looks like, how to test it yourself |
| `docs/EVAL_SEED_QUESTIONS.md` | 50 starter test questions for the evaluation harness |
| `docs/CV_AND_LINKEDIN.md` | How to put the finished project on your CV, LinkedIn and in interviews |
| `.env.example` | The environment variables the app needs (copy to `.env`, never commit `.env`) |
| `.gitignore` | Keeps secrets and junk out of git |

---

## Step 0 — Things to install (one time)

1. **VS Code**: https://code.visualstudio.com
2. **Git**: on Mac run `xcode-select --install` in Terminal if `git --version` doesn't work.
3. **Node.js 20 or newer** (needed for GSD and the frontend): https://nodejs.org (LTS version).
4. **Python 3.12** and **uv** (fast Python package manager):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   uv python install 3.12
   ```
5. **Docker Desktop** (runs PostgreSQL locally): https://www.docker.com/products/docker-desktop
6. **Claude Code**: install the "Claude Code" extension in VS Code (Extensions panel → search "Claude Code"), or in a terminal:
   ```bash
   npm install -g @anthropic-ai/claude-code
   ```
   Then run `claude` once in a terminal and log in.

## Step 1 — Accounts and keys (free)

| Key | Where | Why |
|---|---|---|
| ENTSO-E security token | Register at https://transparency.entsoe.eu, then email/request "Restful API access" (see their help pages). Approval can take a few days, **so do this first**. | Official source of Finnish day-ahead prices, with history |
| Anthropic API key | https://console.anthropic.com | The agent's LLM. Set a small monthly spending limit (for example €10). |
| Langfuse keys | https://cloud.langfuse.com (free Hobby plan) | Tracing and evaluation dashboards |
| GitHub account | You already have one (AbdulZeeshan688) | Code, CI, daily data job |
| Netlify | You already use it | Frontend hosting |
| Render or Fly.io | Free tier | Backend hosting (Phase 8) |

While waiting for the ENTSO-E token you can still start: Phase 2 uses the free porssisahko.net API as a no-key source first.

**Never paste API keys into the Claude chat.** Put them only in your local `.env` file.

## Step 2 — Create the project folder

```bash
mkdir spotwise-fi && cd spotwise-fi
git init
```
Copy everything from this kit into that folder (including the hidden `.gitignore` and `.env.example`). Then:
```bash
cp .env.example .env      # then open .env and fill in your keys
git add . && git commit -m "Add project kit"
```
Create an empty repo on GitHub called `spotwise-fi` and push to it.

Open the folder in VS Code: `code .`

## Step 3 — Install GSD

In the VS Code terminal, inside the project folder:
```bash
npx get-shit-done-cc@latest
```
Pick **Claude Code** as the runtime and **local** (this project) as the install location when it asks.

Then start Claude Code in the same terminal: `claude` (or open the Claude Code panel in VS Code). Type `/gsd:help` to check that the commands are there. GSD versions change a bit, so if a command name below differs, `/gsd:help` shows the current one.

## Step 4 — Start the project in GSD

Run:
```
/gsd:new-project
```
When GSD asks what you want to build, answer with this (copy-paste):

> Build the project described in @docs/PROJECT_BRIEF.md. Follow @CLAUDE.md for all conventions. Use the requirements (with their IDs) and the 8-phase roadmap from the brief as the starting point. Keep v1 scope exactly as written; put everything in the "Out of scope / v2" list into a v2 milestone, not v1. I am a junior developer, so keep plans small and explain decisions briefly.

Answer GSD's follow-up questions using the brief. When it offers domain research, say **yes**: it will check the current price APIs (they changed to 15-minute data in 2025).

At the end you'll have a `.planning/` folder with `PROJECT.md`, `REQUIREMENTS.md`, `ROADMAP.md` and `STATE.md`. **Read `ROADMAP.md` and compare it with the brief.** If phases are missing or merged differently, tell Claude to fix it now. It's cheap to change the plan, expensive to change the code.

Commit: `git add . && git commit -m "GSD project planning"`

## Step 5 — The loop for every phase (1 to 8)

For phase N:

```
/gsd:discuss-phase N      ← paste the "discuss" text for phase N from docs/PHASE_GUIDE.md
/gsd:plan-phase N         ← read the PLAN files it writes; say if anything looks wrong
/gsd:execute-phase N      ← Claude writes the code and commits each task
/gsd:verify-work N        ← you test it by hand using the checklist in PHASE_GUIDE.md
```
Then:
- Run the tests yourself: `uv run pytest` (backend) and `npm test` in `web/` (Phase 7+).
- Push: `git push`.
- Type `/clear` before starting the next phase, so Claude starts fresh. GSD remembers progress in `.planning/STATE.md`.

Other useful commands:
- `/gsd:progress`: where am I, what's next.
- `/gsd:pause-work` / `/gsd:resume-work`: stop in the middle and continue another day.
- `/gsd:quick`: small fixes ("the chart y-axis label is wrong").
- When all 8 phases are done: `/gsd:audit-milestone`, then `/gsd:complete-milestone`.

## Step 6 — Rules that keep you out of trouble

1. **One phase per session.** Long sessions make Claude forget and drift.
2. **Read every PLAN before executing.** Ask "why?" about anything you don't understand. You'll be asked about it in interviews.
3. **Don't let Claude delete tests to make them pass.** If it tries, stop it.
4. **Commit after every phase.** If something breaks badly: `git log`, then `git reset --hard <last good commit>`.
5. **Secrets only in `.env`.** If a key ever lands in git, revoke it right away and make a new one.
6. **Understand the code.** After each phase, ask Claude: "Explain the 3 most important files from this phase like I'm going to be interviewed about them." Write down the answers.

## Rough timeline (evenings, about 2 hours a day)

| Week | Phases |
|---|---|
| 1 | 1 Foundation, 2 Ingestion, 3 Data quality |
| 2 | 4 Price tools, 5 Agent |
| 3 | 6 Evaluation harness, 7 Web app |
| 4 (half) | 8 Deploy, README, demo, LinkedIn post |

A working version by the end of week 3 is the goal. Polish can wait.

## Expected costs

- Everything except the LLM is free on free tiers.
- LLM: development and evaluation runs with a small/cheap model usually cost a few euros in total. Set a spending limit in the Anthropic console, and run the full eval suite only when you need it (it's a manual GitHub Action, not on every push).
