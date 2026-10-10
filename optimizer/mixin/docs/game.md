# webDiplomacy: the game

What a bot author needs to know about the game itself: the board, phases,
orders, how a game ends, how it is scored, and the variants and leagues. The bot
contract (launcher, HTTP routes, LLM sidecar) is in [protocol.md](protocol.md);
hosted specifics are in [platform.md](platform.md).

**Source of truth.** The Coworld runs the **unmodified** upstream webDiplomacy
server, pinned as a submodule in
[Metta-AI/coworld-webdiplomacy](https://github.com/Metta-AI/coworld-webdiplomacy).
Its docs are the long references; this file summarizes them. The links below
point at commit `b4aca73` so they match what this lab was written against.
Check the hosted version with `coworld games` before relying on a detail that
may have changed.

- [Player protocol](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/docs/protocol.md): lifecycle, scoring, `results.json`
- [Upstream bot API](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/docs/upstream-bot-api.md): routes, orders, votes, with citations into the upstream PHP
- [Replay format](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/docs/replay.md)
- [Variants and config](https://github.com/Metta-AI/coworld-webdiplomacy/blob/b4aca7310d1de95fe3fc6f61606bfe7ac05335ab/coworld_manifest_template.json) (`variants`, `config_schema`)

You are free to write your own longer references in this lab (for example a
`docs/map.md` of adjacencies you have verified). Cite where each fact came from.

## The board

Classic Diplomacy for seven players. Each seat plays one **power** (webDip calls
it a country):

| ID | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| Power | England | France | Italy | Germany | Austria | Turkey | Russia |

- Units are **armies** (land) and **fleets** (sea and coasts). One unit per
  province.
- 34 provinces are **supply centers (SCs)**: 3 home centers per power, 4 for
  Russia, and 12 neutral (counted from upstream
  `webdiplomacy/variants/Classic/install.php`).
- In winter you build or remove units so your unit count equals your SC count.
  You can build only on an empty home center that you still own.
- A power that owns **18 SCs wins alone** (a "solo").
- There is no dice and no turn order. Every power writes its orders in secret;
  the server resolves them all at once ("adjudication").

## Phases and the game clock

- **Turn** counts from 0. Even turns are Spring, odd turns Autumn.
  **Year = 1901 + turn // 2.** Spring 1901 is turn 0.
- Phases: `Pre-game`, **`Diplomacy`** (movement), `Retreats`, `Builds`,
  `Finished`. Upstream calls movement `Diplomacy`; the viewers label it
  **Movement**. API requests must use the raw value `Diplomacy`.
- Winter adjustments happen in the `Builds` phase after an Autumn.
- Each phase has a deadline (whole minutes, set by the variant). A phase ends
  **early when every seat is marked Ready**.
- A seat that sends nothing keeps the server's defaults: holds in movement,
  disbands in retreats, skipped builds. In this Coworld the game type is
  `MemberVsBots` with seven ordinary `User` accounts, so a silent seat does not
  delay the phase or go into civil disorder.

`(turn, phase)` is the clock that joins replays, results and our own logs.

## Orders

Order types: `Hold`, `Move`, `Support hold`, `Support move`, `Convoy`,
`Retreat`, `Disband`, `Build Army`, `Build Fleet`, `Destroy`, `Wait`. Each order
names territories by numeric ID from the map file `variant.json`.

- Support targets use the **parent province** ID. Fleet moves into split-coast
  provinces (Spain, Bulgaria, St Petersburg) use the **child coast** ID.
- A convoyed move must list its convoy path. The server checks the path; it does
  not find one for you.
- There is **no route that lists legal orders**. Bots compute them from
  `variant.json`. The coworld's `players/legal_orders.py` (inside the player
  base image) follows upstream's validators and is tested.
- **Invalid orders are dropped silently and the server still returns HTTP 200.**
  The unit keeps its previous order, usually Hold. Always diff the saved orders
  against what you sent. An unknown `terrID` is the exception: it returns 400.
- `game.json` marks unowned SCs with `ownerCountryID: 0`. Untouched neutral
  provinces can be missing from its territory list; treat them as empty and
  unowned.

## Press and votes

- In press variants (`press: Regular`), a power can message one power or
  everyone (`toCountryID` 0). Gunboat (`NoPress`) allows no messages.
- Each seat reads only its own private press. Public replays contain only public
  press.
- A **draw** needs a Draw vote from every surviving power. Votes count here
  because every seat is a `User` account. Voting Draw does not mark you Ready.

## How a game ends

In order of precedence:

1. **Solo:** one power reaches 18 SCs.
2. **Agreed draw:** every survivor votes Draw.
3. **Year cap:** the variant's `end_year`. The adapter ends the game as a draw
   at the first state it observes after that year's Autumn and its retreats.
   The actual final turn can be that Autumn's Builds or the next Spring;
   `results.json` records it.
4. **Time budget:** the episode ends after `episode_budget_seconds` (default and
   maximum 5,910 s, about 98 minutes) even if the year cap was not reached.
5. **Cancellation** (rare): upstream erases the game.

A **bot is killed when the game ends.** The launcher stops the bot process at
game over. Write state and summaries as you go; an end-of-game summary may never
be written.

## Scoring

The default rule is `sum_of_squares`:

- **Solo:** the winner scores 1, everyone else 0.
- **Otherwise:** each surviving power scores **SC² / (sum of SC² over all
  survivors)**. Eliminated powers score 0.
- **Cancelled:** 1/7 each. If every survivor has zero SCs, equal shares.

Scores in one game sum to 1, so **parity is 1/7 = 0.143**. Because the share is
quadratic, being the **largest** survivor matters most. For example, 7 SCs
when the other six survivors hold 4 to 5 each already scores about 0.25 to
0.30. Losing two centers when you are big costs far more than gaining two when
you are small.

Other rules exist in the config (`supply_centers`: SC / total SC; `draw_size`:
equal shares to survivors) but the leagues use the default.

## Slots and countries

- The roster **slot** (0 to 6) is not the power. The adapter assigns powers by a
  seeded shuffle per episode, unless the optional `countries` setting pins them
  (merged in `b4aca73`, pending republish; see the eval-design binding).
  `WEBDIP_COUNTRY_ID` tells the bot its power.
- **`results.json` is in slot order.** `results.countries[slot]` is that slot's
  power ID.
- Powers differ a lot in strength. In the 2026-10 press field France averaged
  about three times England's score (see [strategy.md](strategy.md)). Always
  compare a seat with the field's average **for the same power**.

## `results.json`

| Field | Meaning |
|---|---|
| `scores` | Seven numbers in **slot order** |
| `countries` | `countries[slot]` = power ID (1 to 7) |
| `outcome` | `won`, `drawn` or `cancelled` |
| `reason` | Why play ended: `end_year`, `episode_timeout`, `cancelled`, or `won`/`drawn` when upstream ended it. Easy to skip; check it |
| `members` | Upstream member rows by country: `countryID`, `status`, `supplyCenterNo`, `unitNo`. **Values are strings** |
| `seed` | Episode seed used |
| `final_state` | Upstream game row at the end (`null` when cancelled) |
| `transitions` | Each observed `(turn, phase, process_status)` change with elapsed seconds |
| `gamemaster_calls` | Timing summary of upstream processing |

**Final SC counts come from `results.json` `members[].supplyCenterNo`.** The
replay's final `Finished` history entry shows ownership from *before* the last
Autumn, so it is wrong for the last year.

## Variants

From the manifest's `variants` (verified at `b4aca73`):

| Variant | Press | Movement / retreat+build minutes | Ends after | Used by |
|---|---|---|---|---|
| `classic-press` | Regular | 4 / 1 | 1908 | webDiplomacy league |
| `classic-gunboat` | none | 1 / 1 | 1910 | webDiplomacy Gunboat league |
| `classic-press-short` | Regular | 3 / 1 | 1904 | health checks, smoke tests |
| `classic-live-human` | Regular | 7 / 2 | 1904 | human lobbies |

A full `classic-press` game has 16 movement phases (1901 to 1908).

## Leagues

| League | ID | Variant |
|---|---|---|
| webDiplomacy (main, full press) | `league_1bccc63d-cd0a-47d7-92d7-e762797b5f1c` | `classic-press` |
| webDiplomacy Gunboat | `league_428e91e5-ee25-4f9c-be5e-a4fc4f993f17` | `classic-gunboat` |

As of 2026-10-06 (lab observation, not re-verified): one round per day, one
player per user, ranked by **mean score**. Empty seats are filled from each
league's **filler roster**. Read the live settings with
`coworld leagues <league_id> --json` before relying on these.

## Timing

- Hosted full `classic-press` games took **60 to 100 minutes** in the 2026-10
  lab: about 61 minutes by one measurement, 80 to 100 by another. LLM seats
  rarely all mark Ready, so press phases usually run their full 4 minutes.
  Measure your own.
- Local gunboat games with bots that mark Ready take 40 to 45 seconds. Local
  games with the search policy take about 4.5 minutes.
