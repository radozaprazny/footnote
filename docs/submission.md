# Submission materials

The texts of the Innovation Studio project page and the script of the demo video. The owner
pastes, records and submits them; nothing here is published by itself. Each text to paste is a
code block: copy what is inside it.

## Project page

**Title** (48 of 140 characters):

```text
Footnote: match intelligence that shows its work
```

**Tagline** (273 of 300 characters):

```text
Agents explain a synthetic football match, and a deterministic Guard checks each number and judgement phrase they write against the stats engine before it reaches the screen. Analyst and Fan personas, a favourite club, English and Slovak. Built for Best Multi-Agent System.
```

**Keywords**:

```text
multi-agent system, Best Multi-Agent System, Microsoft Agent Framework, Microsoft Foundry, Model Context Protocol, Azure Container Apps, explainable AI, sports broadcast, real-time overlays, personalization, synthetic data
```

**Challenge:** The Synthetic Match Insights Engine for Premier League Studio

**Open for others to join:** No. **Writing code:** Yes.

**Description** (the pitch, Markdown):

```markdown
**Footnote** turns a synthetic football match into explainable, personalized on-screen intelligence. Every line on screen has a footnote with its evidence.

**Try it:** https://ca-matchlens.niceglacier-670016e8.swedencentral.azurecontainerapps.io/ (testing instructions in the README).

**The problem.** A language model in a live broadcast can invent a number, or a judgement the match does not support, and on air one wrong number is a correction.

**What we built.** A pipeline with five stages. A seeded generator writes match events and tracking. A deterministic stats engine turns them into facts, each with the event or frame ids it comes from, and into fixed judgement phrases. Workflows on **Microsoft Agent Framework** explain each key moment: a Moment Detector (code) finds it; an Analyst (Claude on **Microsoft Foundry**) reads its facts through an **MCP** server and drafts a caption; a Persona Editor rewrites it for fans, a Recap Writer sums the match up at full time and a Translator writes Slovak. A deterministic Guard judges every draft against the engine and sends a refused one back with machine-readable reasons; retries, fallbacks and a circuit breaker keep a card on screen. The agents share one case per moment, in which an unverified narrative cannot be represented, and every handoff is logged.

**What you see.** The page on **Azure Container Apps** replays three matches live, with the narratives the agents wrote with Claude on Foundry beforehand; the server judges each logged text again before it shows it. Pick an Analyst or a Fan persona, a favourite club, and English or Slovak.

**Measured.** 28 of 28 narratives passed the Guard at the first attempt on Claude Sonnet 5.5 and on Claude Haiku 5.5; 62 of 62 Slovak translations passed, one after a retry; all the model calls of the project through 25 October cost €3.43.

Category: **Best Multi-Agent System** (Best Multi-Agent Orchestration).
```

Pass 2, after the first Save: the repository URL, the video's URL and the cover image.

## Demo video

Under 2 minutes: the shots end at 1:50, with 210 words of voice-over at a calm pace.
No music and no logos; record in a clean browser profile (no bookmarks bar, extensions or other
tabs), crop the README to its diagram, and give the terminal a neutral prompt. Footage: the live
page in a 1920×1080 browser, the README's architecture diagram, and one terminal shot. Times are
targets.

| Time | Picture | Voice-over |
|---|---|---|
| 0:00–0:08 | The picker of the live page, the title "Footnote". | "This is Footnote. Every line on screen has a footnote with its evidence." |
| 0:08–0:22 | Pick Vellbridge Town as the favourite club, open its match, speed 30×. Cards enter the rail; the club's cards lead. | "A synthetic match plays live. Claude models on Microsoft Foundry wrote its key moments beforehand, and the page replays them in time, your favourite club first." |
| 0:22–0:38 | Open a card's "✓ verified" chip: the fact and event ids appear. Click the card: its place lights up on the pitch. | "Every number comes from a deterministic stats engine, never from a model, and every claim cites the events or tracking frames behind it, so you can check each one." |
| 0:38–0:52 | Switch Analyst to Fan, then EN to SK. The same card changes its words twice. | "The same verified facts reach an analyst and a casual fan as two different experiences, in English or Slovak." |
| 0:52–1:12 | The README's architecture diagram; highlight the agents one by one. | "Under the hood: Microsoft Agent Framework workflows. A Moment Detector finds the goals, saves and shots off the woodwork. The Analyst reads the facts through an MCP server and drafts a caption; a Persona Editor, a Recap Writer and a Translator follow, all sharing one case per moment." |
| 1:12–1:30 | The terminal shot below, with English captions on screen: the first draft ends "Saltreach FC má 59% navrch", "Saltreach FC are on top at 59%" (refused); the second "momentum Saltreach FC je 59%", "Saltreach FC's momentum is 59%" (passed). | "Each draft must pass the Guard: plain code, not another model. Here it refused a Slovak recap that put one club on top without the engine's reading, and the Translator fixed it on the second try." |
| 1:30–1:44 | Full time, by a cut in the edit or by opening `?match=m0&team=vel&speed=300&hz=1` about 20 s before (full time comes about 20 s in): the recap card, then its Slovak version. Then the URL bar of the live page. | "At full time the Recap Writer sums the match up. The page runs on Azure Container Apps, and all the agents' model calls so far cost about three and a half euros." |
| 1:44–1:50 | The title again with the repository URL. | "Footnote: match intelligence that shows its work." |

The terminal shot, pasted into a terminal at the repository root:

```
python3 -c "import json
for line in open('demo/runs/m1/translate.sk.jsonl'):
    h = json.loads(line)
    if h['to'] == 'render' and h['state']['moment_id'] == 'recap':
        for t in h['state']['translations']:
            if len(t['attempts']) == 2:
                for a in t['attempts']:
                    print(a['verdict']['passed'], [r['code'] for r in a['verdict']['reasons']])
                    print('   ', a['draft']['text'])"
```
