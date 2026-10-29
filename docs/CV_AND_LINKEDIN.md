# After it's built: CV, LinkedIn, interviews

Fill in the **real numbers** from your latest eval report. Never put numbers you didn't measure.

## CV — Projects section (put it first)

**SpotWise FI — AI Agent for Finnish Electricity Prices** · Live project · 2026
- Built a daily data pipeline (Python, PostgreSQL, GitHub Actions) that ingests Finnish day-ahead prices from the ENTSO-E API, handling 15-minute and hourly data and DST days, with idempotent upserts.
- Added automated data-quality checks (completeness, duplicates, spikes, staleness) with a status API.
- Built a LangGraph agent that answers price questions only through typed, tested tools (cheapest window, stats, cost estimates), with guardrails against made-up numbers.
- Built an evaluation harness: [N] golden questions on a frozen dataset, LLM-as-judge, Langfuse tracing and a CI regression gate. Numeric accuracy **[X]%**, refusal accuracy **[Y]%**.
- React + TypeScript front end with a live price chart and streaming chat; deployed on Netlify + Render.
- Live demo: [link] · Source: [GitHub link]

Skills line to add: `LangGraph · AI evaluation · Langfuse · TypeScript · GitHub Actions · Data quality`

## LinkedIn
1. **Featured section:** add the demo link with the GIF as the image.
2. **Projects section:** same text as the CV, shorter.
3. **Post** (when it's live). Structure: the problem in one line → what you built → one honest lesson → the eval number → link. Example opening:
   > Finland's electricity price now changes every 15 minutes. I built an AI assistant that tells you when it's cheapest, and I measured how often it's right.

   Then: *"The hardest part wasn't the AI. It was daylight-saving days with 25 hours, which broke my first version."* People like honest lessons.
4. Add **LangGraph**, **TypeScript** and **AI Evaluation** to your Skills.

## Interview — 2-minute story
1. **Problem:** spot prices change every 15 minutes; people want to know when to use electricity.
2. **Design choice:** math in tested code, words from the LLM, so the agent can't invent numbers.
3. **Hard parts:** DST days, the switch from hourly to 15-minute data, and making evals deterministic with a frozen dataset and a frozen clock.
4. **Measurement:** [X]% numeric accuracy on [N] questions; the CI gate fails if it drops.
5. **What I'd do next:** price forecasting, tariffs and transfer fees, Finnish UI.

## Questions to prepare (you'll get these)
- Why LangGraph instead of a simple loop?
- How do you stop the LLM from making up numbers?
- How does your eval decide whether an answer is correct?
- What's wrong with LLM-as-judge, and how did you limit it?
- What happens if the ENTSO-E API is down?
- How would this scale to all Nordic zones?
- What would you test first if a user reports a wrong price?

## Jobs this project matches directly
If Insurance (Generative AI Specialist), IPRally (Data Engineer), Capalo AI (AI Engineer, Asset Onboarding), EOS (Software Engineer), Smartly (Launchpad), Virta (Business Operations), and similar Python/AI/data roles. Mention it in every cover letter from now on.
