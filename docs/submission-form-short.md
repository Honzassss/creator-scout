# HQ submission form (short version)

## Project name
Creator Scout

## One-line pitch
Check a social-media creator for your business goal: every fact sourced, gaps stated, no scores.

## What it does
A small business owner, say a bakery in Brno, wants to sponsor a local Instagram or TikTok creator. She is not a marketer, and under Czech advertising law she shares liability for unlabeled ads, so she needs to know what the creator actually posts and with whom.

She gives Creator Scout one account, one anchor (city, website or company ID) and her goal. The agent pulls public data through Apify actors, checks it is the account she means (namesakes and look-alikes are set aside), and writes a report: facts with their source, inferences that cite those facts, and gaps that become questions for a first meeting. It flags collaborations with competitors she names and drafts an outreach message that is never sent.

Switch the goal, bakery to fitness studio, and the report is rebuilt from the same data and shows what changed. No scores, no "best creator": she decides.

## What works end-to-end
Input: @kamvbrne (a public Brno city-guide account), anchor Brno, goal "bakery in Brno", two bakery competitors.

Output: identity "likely" with its signals, 10 unrelated news results set aside, the check "no competitor collaboration" not met with links to the co-authored posts, facts / inferences / gaps with confidence, meeting questions, outreach marked NOT SENT. Switching to "fitness studio" rebuilds the report in under 0.4 s with no new fetch and lists what changed.

Measured on 2 real accounts researched live through Apify on 9 Oct: 83/83 facts have a source URL, 134/134 quotes found in the fetched data, 501/501 sources labeled live, cache or mock. Sensitive criteria refused 9 of 10.

## What is simulated, missing or fragile
- The video replays the live recording from cache (labeled). The discovery funnel shown is MOCK, with fictional creators.
- The live demo link is a static MOCK replay without a backend.
- Real discovery was not re-run live after our last engine fixes.
- Meta Branded Content returned nothing for Czech brands; we rely on paid labels, co-authored posts, ad hashtags and discount codes.
- LLM: a free OpenRouter model; claim extraction fell back to rules in both real runs. Claude was not run live.
- The sensitive-content filter is keyword based: it caught 16 of 20 on our own test list.
- Age is a gap, not a filter: the platforms do not expose it.

## Stack and partner tools
Apify, Python, FastAPI, React, TypeScript, Vite, Tailwind CSS, OpenRouter, Vercel

## GitHub repository
https://github.com/Honzassss/creator-scout

## Live demo link
https://creator-scout-demo.vercel.app

## Unlisted YouTube link
[YOUTUBE URL]

## ElevenLabs
Not used: leave unticked.
