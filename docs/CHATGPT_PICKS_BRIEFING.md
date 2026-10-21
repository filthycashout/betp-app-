# ChatGPT Picks Briefing

The read-only `GET /v1/chat/picks` endpoint combines the app's existing today, Best 12, and best-three-leg parlay outputs into one response intended for a chat-based presentation.

## Request

```http
GET /v1/chat/picks
GET /v1/chat/picks?date=2026-10-20
```

The date is optional and uses `YYYY-MM-DD` in the app's `America/Los_Angeles` calendar. Without a date, the today section uses the existing four-day today feed. With a date, it requests that day's schedule. The Best 12 and parlay sections use the selected target date.

## Response contract

- `status` is `FETCHED`, `PARTIAL`, or `UNAVAILABLE` based on whether the three sections returned.
- Each section is either `available` with the original source payload, or `unavailable` with only an exception-class code. Raw exception messages and provider details are not exposed.
- `generated_at_utc` is when this briefing was assembled. It is **not** evidence that every market quote is fresh.
- Original market timestamps, book names, prices, model state, availability markers, and evidence metadata remain in their underlying section payloads.
- The endpoint does not create substitute picks if a section fails. Empty or unavailable results must be shown as such.
- `automatic_wagering` is always false. Model-promotion and evidence-admission gates remain authoritative.

## Suggested chat presentation

When this response is available to a chat client, present:
1. Data status and target date, with the actual market-evidence timestamp called out separately from the response generation time.
2. Best verified picks, grouped by sport and market, showing selection, offered line/price, bookmaker, quote timestamp, probability method, and model state only when supplied by the API.
3. Best 12 board, retaining unavailable slots rather than filling them with guesses.
4. Three-leg parlay cards only when the API supplies eligible legs; show dependence as unknown when it has not been established.
5. Missing feeds, stale quotes, failed sections, and any promotion gates that remain blocked.

Do not call a pick a “lock,” promise returns, imply independent parlay legs without evidence, or claim a model is promoted when its gate has not passed.

## Important integration limit

This endpoint makes a single, stable API contract available to a chat integration. A ChatGPT conversation can present live picks only when the deployed endpoint is reachable through an enabled connector/action or other available retrieval mechanism. Merely committing this endpoint does not automatically connect a repository to every ChatGPT conversation. Verify production reachability and the production contract guard before relying on it.
