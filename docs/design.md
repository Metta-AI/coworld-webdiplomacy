# Design and rationale

Why this Coworld is built the way it is. For how the pieces fit together, see
[architecture](architecture.md); for behavior and contracts, the
[README](../README.md), [protocol](protocol.md) and
[upstream bot API](upstream-bot-api.md). This page records the reasoning behind
them and the options that were rejected.

## Goals

- **Run webDiplomacy as the live site runs it.** Use its rules, adjudicator,
  votes, deadlines and gamemaster loop without changing upstream code.
- **Bots are compatible with the live webdiplomacy.net API in both directions.**
  A bot that plays here also plays on the live site with a different base URL
  and API key.
- **Humans and bots can play in the same game,** through upstream's own board.
- **Run as a certified, hosted Coworld** with ladder leagues.
- **Fit a useful game, including LLM press, in one episode** of at most 100
  minutes.
- **Stay close to upstream.** Moving to a new upstream commit should be routine.

## Non-goals

- **Changes to upstream code.** The `webdiplomacy/` submodule is never edited;
  generated files such as `config.php` live only in the image.
- **Multi-day games.** These need the platform's Persistent Coworld mode, in
  which a game runs continuously and the platform records periods of play as
  episodes. That is separate, larger work.
- **Variants other than Classic.** Upstream lets bots play only variants 1, 15
  and 23 (`webdiplomacy/config.sample.php:259-268`); 15 and 23 are two-player maps.

## Key decisions

**Upstream's gamemaster loop advances the game; the adapter stays outside it.**
The upstream Node SSE server calls `gamemaster.php` about once a second, exactly
as on the live site. Phase processing, early end when everyone is Ready, votes
and missed-deadline handling are therefore identical to webdiplomacy.net by
construction. The adapter only creates the game, starts it, ends it at the year
cap, and records results and replay. An earlier draft had the adapter schedule
phases and apply votes; that copied `gamemaster.php` and could drift from the
live site, so it was dropped.

**Seats are `User` accounts in a `MemberVsBots` game.** With `Bot`-type accounts,
votes never pass and upstream forces a draw at the first phase change
(`webdiplomacy/gamemaster/gamemaster.php:490`,
`webdiplomacy/gamemaster/game.php:883-898`). `MemberVsBots` is the type the live
site uses for humans against bots: a missed deadline does not extend the phase
and a silent seat simply holds (`webdiplomacy/gamemaster/game.php:596-597`).
The account type does not change what the API lets a player do.

**The WebSocket carries only hello and presence; all play is upstream HTTP.**
A Coworld-specific move or press protocol would make every bot Coworld-specific.
Instead the seat's Coworld token is also its webDip API key, and the launcher
hands the bot `WEBDIP_URL` and `WEBDIP_API_KEY`. Hosted player pods can reach
any path on the game's port because platform network rules work on ports, not
paths, so bots talk to the same host and port as the WebSocket.

**Public replay, private press per player.** Replay and spectators see only what
a logged-out visitor to webdiplomacy.net sees. Each launcher archives its own
seat's private press to the player log and artifact, which the platform shows
only to that policy's owner and Softmax staff. This needs no Observatory work.

**One container holds every upstream service.** The platform allows one game
container, so nginx, PHP-FPM, MariaDB, Redis, the Node SSE server and the adapter
share it. nginx is the only public listener and serves an explicit route list;
everything else (admin pages, sandbox routes) returns 404.

**The database is installed at image build time.** A fresh upstream install takes
minutes, and local certification gives the container 60 seconds to become
healthy. The image bakes the schema, Classic map and variant info; boot only
generates secrets and unlocks the gamemaster.

**A small custom supervisor instead of supervisord or s6-overlay.** Those keep
services alive indefinitely and expect to manage users. Here any unexpected
daemon exit must fail the episode, shutdown must be ordered, and a clean run
must exit 0. Hosted game containers have every Linux capability removed, so
processes cannot switch users; they keep root identity without capabilities
(see README, *Runtime*).

**Scoring defaults to sum-of-squares.** Upstream's own non-solo formula
(`webdiplomacy/objects/scoringsystem.php:123-140`): each survivor scores SC²
divided by the total of surviving SC². `draw_size` and `supply_centers` are
configurable alternatives.

## Alternatives rejected

| Alternative | Why rejected |
| --- | --- |
| Another Diplomacy engine, such as the Python `diplomacy` package | Its bots are not compatible with webdiplomacy.net |
| Extract upstream's adjudicator into a separate engine | Most rules are written in SQL; this becomes a reimplementation |
| Adapter as phase scheduler and vote counter | Duplicates `gamemaster.php` and can drift from the live site |
| Coworld-specific protocol for moves and press | Makes every bot Coworld-specific |
| Game-hosted players (the game runs uploaded player files) | Cannot run arbitrary bot images with their own dependencies and the model sidecar |
| Members game with `Bot`-type accounts | Votes cannot pass; missed deadlines extend phases |
| Fork upstream and delete the web code | Makes every upstream update harder; nginx route filtering achieves the same exposure |

## Updating upstream

Upstream changes in bursts; most of its September 2026 commits were the API
redesign. The code of ours that touches upstream is small: the `php/wdc_*.php`
scripts, `config/webdip.php` and the nginx route list in `config/nginx.conf`.
Boot also patches one line of upstream's `config.sample.php` (the error-log
directory) and fails loudly if that line changes.

To move to a new upstream commit: update the submodule, rebuild the image (which
reinstalls the database), then run the boot, episode, compatibility and browser
checks in the README and certify. Recheck the line citations in
[upstream-bot-api.md](upstream-bot-api.md).

## Known risks

- **Load.** PHP requests have a 4-second execution limit
  (`webdiplomacy/header.php:147`), and upstream documents a `game/sendmessage`
  deadlock under heavy concurrent writes (`webdiplomacy/doc/gamedata/02-spec.md:550-551`).
  Chatty LLM press bots are the most likely trigger.
- **Background tasks.** Upstream's gamemaster also runs site-wide background
  tasks such as rating updates and idle-game cleanup
  (`webdiplomacy/gamemaster/backgroundTasks.php`). With one game per database
  they are cheap, but an upstream change there could touch the episode's game.
- **Older bots do not work.** The 2026-09-20 upstream API redesign removed the
  read routes that CICERO, Dora and the pip `diplomacy` client use
  (`webdiplomacy/doc/gamedata/02-spec.md:596-599`). Only bots written for the
  current API play here, which is also true on the live site.
- **Time.** LLM press games can be slow; the hosted model sidecar allows 30 calls
  per minute per seat. Phase lengths and the year cap are configurable per
  variant.
