# Tested, no result yet — webDiplomacy

Levers that were built and measured and ended **inconclusive**: |z| < 2, so
neither confirmed nor refuted. They are not closed, and `closed_levers.md` is the
wrong place for them (it holds only what the numbers killed). They are listed here
because an experiment record that ends "inconclusive" otherwise leaves no trace
where the next proposal looks, and the next agent proposes the same idea again.

Read this file with `closed_levers.md` before proposing anything. An entry here
tells you two things about a new idea in the same family:

- **A prior on the size.** Size the new test for the effect the last one showed
  (`tools/sizing.py --effect`), or do not run it.
- **What a second try must add.** A stronger dose of the same lever is a fair
  test only with a reason to expect a larger effect. Several small readings of
  the same sign, each inside the noise, are not that reason: three same-sign
  results at |z| < 1 happen by chance one time in four.

This file ships with no entries: an entry is one lab's measurement against one
field. Add your own when a record closes inconclusive; move an entry to
`closed_levers.md` when a later test refutes it, and delete it when one confirms it.

Format (the block below is an example of the fields, not an entry):

```
## <lever name>                                    tested YYYY-MM-DD
**Mechanism:** <what the change was, and the setting or code location>
**Read:** <the measured difference with n, SE and z, the field set, and whether the mechanism fired>
**Could see:** <the smallest effect that run could have shown>
**A next test needs:** <what would make another run worth its games>
```

---
