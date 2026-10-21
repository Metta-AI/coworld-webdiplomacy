# webDiplomacy: the game

What a bot author needs to know about the game itself: the board, phases,
orders, how a game ends, how it is scored, and the variants and leagues. The bot
contract (launcher, HTTP routes, LLM sidecar) is in [protocol.md](protocol.md);
hosted specifics are in [platform.md](platform.md).

**Source of truth.** The Coworld runs the **unmodified** upstream webDiplomacy
server, pinned as a submodule in
[Metta-AI/coworld-webdiplomacy](https://github.com/Metta-AI/coworld-webdiplomacy).
Its docs are the long references; this file summarizes them. The links below
point at commit `fd03252` (Coworld 0.7.16), which this lab was checked against.
Check the hosted version with `coworld list` before relying on a detail that
may have changed.

- [Player protocol](https://github.com/Metta-AI/coworld-webdiplomacy/blob/fd03252927bfcf36b2d0a03ba83fe36e057f8201/docs/protocol.md): lifecycle, scoring, `results.json`
- [Upstream bot API](https://github.com/Metta-AI/coworld-webdiplomacy/blob/fd03252927bfcf36b2d0a03ba83fe36e057f8201/docs/upstream-bot-api.md): routes, orders, votes, with citations into the upstream PHP
- [Replay format](https://github.com/Metta-AI/coworld-webdiplomacy/blob/fd03252927bfcf36b2d0a03ba83fe36e057f8201/docs/replay.md)
- [Variants and config](https://github.com/Metta-AI/coworld-webdiplomacy/blob/fd03252927bfcf36b2d0a03ba83fe36e057f8201/coworld_manifest_template.json) (`variants`, `config_schema`)

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
4. **Time budget:** the episode ends after `episode_budget_seconds` (default
   5,910 s, about 98 minutes; 8,310 s in `classic-press-extended`) even if the
   year cap was not reached.
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

In a league game the score also sets the order of the entrants, and that order is what
the league's rating moves on ([Leagues](#leagues)): finishing above another entrant
counts the same whether the gap is one center or ten, and everyone on 0 shares last place.

Other rules exist in the config (`supply_centers`: SC / total SC; `draw_size`:
equal shares to survivors) but the leagues use the default.

## Slots and countries

- The roster **slot** (0 to 6) is not the power. The adapter assigns powers by a
  seeded shuffle per episode, unless the optional `countries` setting pins them
  (webDiplomacy Coworld 0.7.9 and later; see the eval-design binding).
  `WEBDIP_COUNTRY_ID` tells the bot its power.
- **`results.json` is in slot order.** `results.countries[slot]` is that slot's
  power ID.
- Powers do not score alike, and how much they differ depends on the field. Always
  compare a seat with the field's average **for the same power** (`wd.py metrics`
  prints it per batch).

## `results.json`

| Field | Meaning |
|---|---|
| `scores` | Seven numbers in **slot order** |
| `countries` | `countries[slot]` = power ID (1 to 7) |
| `roles` | `roles[slot]` = power name (`England` … `Russia`), the same assignment as `countries` (Coworld 0.7.15 and later) |
| `outcome` | `won`, `drawn` or `cancelled` |
| `reason` | Why play ended: `end_year`, `episode_timeout`, `cancelled`, or `won`/`drawn` when upstream ended it. Easy to skip; check it |
| `members` | Upstream member rows by country: `countryID`, `status`, `supplyCenterNo`, `unitNo`. **Values are strings** |
| `seed` | Episode seed used |
| `final_state` | Upstream game row at the end (`null` when cancelled) |
| `transitions` | Each observed `(turn, phase, process_status)` change with elapsed seconds and, from Coworld 0.7.12, `deadline_unix_time`: a phase that ended before its deadline ended early because every seat was Ready |
| `gamemaster_calls` | Timing summary of upstream processing; from 0.7.12 also `phases`, one `{turn, phase, count, max_seconds}` per phase |
| `seat_health` | From 0.7.12, operational: per slot, the seat's `/player` connect, disconnect and reconnect events and `api_requests`. The lab's tools do not read it |
| `timing` | From 0.7.12, operational: seconds spent in each stage of the container's life. The lab's tools do not read it |

**Final SC counts come from `results.json` `members[].supplyCenterNo`.** The
replay's final `Finished` history entry shows ownership from *before* the last
Autumn, so it is wrong for the last year.

## Variants

From the manifest's `variants` (Coworld 0.7.16):

| Variant | Press | Movement / retreat+build minutes | Ends after | Used by |
|---|---|---|---|---|
| `classic-press` | Regular | 3 / 1 (4 / 1 before Coworld 0.7.10; 2 / 1 in 0.7.13 only) | 1908 | webDiplomacy league |
| `classic-gunboat` | none | 1 / 1 | 1910 | webDiplomacy Gunboat league |
| `classic-press-short` | Regular | 3 / 1 (2 / 1 in 0.7.13 only) | 1904 | health checks, smoke tests |
| `classic-live-human` | Regular | 7 / 2 | 1904 | human lobbies |
| `classic-press-extended` | Regular | 5 / 1 | 1910 | lobbies for slow, negotiating bots (Coworld 0.7.18) |

A full `classic-press` game has 16 movement phases (1901 to 1908).

A hosted request can change `end_year` and the phase lengths for its own games
([platform.md, "Shorter games"](platform.md#shorter-games)); such a game is for
health and behaviour checks, not for score.

## Leagues

| League | ID | Variant |
|---|---|---|
| webDiplomacy (main, full press) | `league_1bccc63d-cd0a-47d7-92d7-e762797b5f1c` | `classic-press` |
| webDiplomacy Gunboat | `league_428e91e5-ee25-4f9c-be5e-a4fc4f993f17` | `classic-gunboat` |

Re-resolve the ids with `coworld leagues --json`. As set on 2026-10-15 (read the live
settings with `coworld leagues <league_id> --json` before relying on these): the press
league's round interval is 72 minutes (`round_interval_minutes: 72`; 150 until 2026-10-12,
then 60) and the gunboat league's is a day (1440). The interval is a minimum: a round
starts on the league's fixed grid of slots, and only when the round before it has finished.
A press round takes about 50 to 60 minutes from start to finish, so press rounds usually
start 72 minutes apart, occasionally 144. In both, every entrant plays at least three games in every round
(`ladder.scheduler.min_episodes_per_entrant: 3`): three games while there are seven
entrants or fewer, with fillers from the league's **filler roster** in the empty seats,
and about three more for each further seven entrants (3 × entrants / 7, rounded up),
seated at random with the least-played first (`ladder.scheduler.strategy: balanced_rotation`;
the press league used rating-neighbour seating, `swiss_neighbor`, from 2026-10-13 to 2026-10-15,
which repeated two fixed tables of seven and about doubled the games). Powers are random in every game. Both have `players_per_user: 1`, up to two retries of a failed
episode, and `disqualify_after_consecutive_failures: 3`. The press league caps each
seat's model spend at $0.50 a game (`episode_player_pod_llm_spend_limit_usd: 0.5`; $2 until
2026-10-14). A seat that reaches it gets its model calls refused for the rest of the game. A new
submission becomes the scoring entry at once ("Auto champion: always").

**Ranking is OpenSkill** (`ladder.ranking.algorithm: openskill`, mu 25, sigma 8.33).
Each game is one ranked match: the entrants in it are ordered by score, equal scores
share a place, and each rating moves on that order alone, not on the size of the gap.
Fillers are not rated, so a game with one entrant moves no rating. The leaderboard's MMR
is the cautious figure mu − 3 × sigma, which starts near zero and rises as games come in.
Both leagues' rounds and standings were reset on 2026-10-12 when the ranking changed.

**The press league also rates the powers** (`ranking.role_advantage_sigma: 2.0`, from round 58
on 2026-10-15; the gunboat league does not). Each side of a game is rated as the player plus a
hidden teammate for the power it played, read from `results.json` `roles`, so a strong
power's expected finish no longer counts as the player's skill: finishing well as Austria
moves a rating more than the same finish as France. The power ratings are learned from the
same games and are not published on the leaderboard; MMR is still the player's own
mu − 3 × sigma. Scores are not adjusted. Ratings from before round 58 keep the luck of the
powers drawn then; it fades as new games come in.

- **A round is three games until there are more than seven entrants.** The league's
  daily budget, not the interval, may be what limits how many rounds run in a day.
- **The schedule is not reliable enough to plan on.** Scheduled rounds have been
  skipped. List the rounds that have actually run with `coworld rounds -l <league_id>`.
- **A normal user cannot start a round and cannot make one come sooner; they wait for
  the schedule.** The league owner or a Softmax team member can start one by hand; it
  looks like any other in `coworld rounds` (`scheduled_by: ladder`) and counts in the
  standings.

**What an entry gets you.** Three games per round, with our seat's log, and a rating
that depends on where we finish among the other entrants in each game, not on score vs
par. A handful of
games says nothing about a policy whose versions differ by a few hundredths of score.
Do not enter a league to collect evidence, and do not wait on a round for it: a field
eval against the filler roster is the evidence, and it is also what the `submit`
skill's first-entry rule asks for before an entry. If the user wants an entry in early
anyway, that is their call: write it in the decision record as a departure from the
rule, with the rollback. `fetch_league.py` brings the league's games in beside your evals.

Standings take two steps: `coworld results <league_id>` lists the league's
divisions with their `div_…` IDs, and `coworld results <div_id>` shows that
division's standings. A league's members are not the whole field an eval can
draw on; the filler roster and other uploaded policies also play.

## Timing

As the platform reported it on 2026-10-10/11; `tools/batches.py` prints the same
numbers for your own batches ([platform.md](platform.md#cost-and-duration)).

- A hosted full `classic-press` game ran a **median 61 minutes** (longest 75), and a
  `classic-press-short` game 23 to 27. LLM seats rarely all mark Ready, so press
  phases usually run their full length. Add queueing and platform restarts for
  the wall clock.
- `classic-press` had 4-minute movement phases until Coworld 0.7.10 (2026-10-12) and has 3-minute phases since. The full-game figures here were measured at 4 minutes; at 3 minutes 171 league games played a median 45 minutes (CHANGELOG, Coworld 0.7.13 entry), close to the 48 the rule in [platform.md, "Shorter games"](platform.md#shorter-games) gives. Measure your own with `tools/batches.py`.
- A hosted `classic-gunboat` game took a **median 2.4 minutes of play** (maximum
  6.6), plus its time in the queue.
- Local gunboat games with bots that mark Ready take 40 to 45 seconds. Local
  games with the reference policy's search take about 4.5 minutes.
