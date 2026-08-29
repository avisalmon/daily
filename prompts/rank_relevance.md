# Prompt: score item relevance 0-10 — PLACEHOLDER

## System
Score how relevant this item is to a daily digest about: {{ topics }}.

## Rules
- Return a single integer 0-10 and nothing else.
- 0 = off-topic, 5 = tangential, 10 = must-include headline news.
- Penalize press releases, listicles, and re-published wire copy.

## Input
Title: {{ title }}
Source: {{ source }}
Excerpt: {{ excerpt }}
