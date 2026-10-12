---
title: Private world actions
description: Keep upstream adjudication authoritative while fencing private seat mutations.
---

# Private world actions

## Rules

- Keep the upstream submodule unchanged. Its gamemaster alone advances phases and applies game outcomes.
- Bind exactly the admitted seven seats to their upstream country. Never expose API keys in observations or outputs.
- Expose control only on the runner-owned Unix socket. Keep upstream API keys, signed order contexts and SSE credentials
  inside the host. Serialize controller replacement with commands.
- Return bounded private observations; disclose when message history is truncated. Public replays exclude private press
  and draft orders.
- Fence commands by controller generation, lease and current upstream phase deadline.
- Journal a command before upstream mutation. A crash or ambiguous result remains uncertain and is never applied again.
  Duplicate IDs must preserve content. Verify canonical saved orders because upstream can silently discard invalid orders.
- Treat the resident MariaDB/PHP container as one game's boundary. Destroy it before reuse of the execution slot.
- A lost resident game fails its attempt. Checkpoint restore needs separate qualification; a fresh board cannot replace
  an accepted game.

## Checks

Run adapter tests and `tools.check_participation` against the composed image. Check all seven private seats, private press
visibility, lost acknowledgements, controller replacement, closed windows and upstream adjudication. Qualify repeated
games through Conductor to prove full container cleanup.
