# 4.4 audit - sample for manual review (2026-08-25, 3 named titles)

> **Supersedes two rounds, and replaces them rather than annotating them.**
> `audit-4.4-live.md` (2026-08-07) presented 20 citation slots and audited **18**
> distinct reviews; `audit-4.4-hades-hollowknight.md` (2026-08-10) presented 20
> and audited **19**. Both were drawn *with replacement* — they predate `4d3f3c0`
> (2026-08-14), which added the `seen` set and the `pool[b].pop()` draw — so a
> review could be sampled twice, costing a slot and buying nothing. That is the
> whole defect: a round overstating its own coverage, in a file whose count is
> its entire evidentiary claim (BACKLOG 2026-08-20).
>
> **One round, not two.** Both originals audit Hades, so their pools share all 40
> of its cited reviews. Regenerating them separately would present 40 slots and
> audit ~38 distinct reviews — the same defect one level up — and would fail
> `check_sample_overlap.py` on the pair. This round covers all three distinct
> titles once.
>
> The originals are preserved byte-identical at `evals/superseded-audits/`.

Generated from an explicit appid list, not a batch night: 367520, 1145360, 1547000. These titles are not in data/batch_state.json, so no date-scoped round can reach them.

Automated QR-4 has already passed on every citation in this set (28,035 citations across 538 verdicts, automated QR-4 run 2026-08-24, PASS (rc=0)). This sample is the HUMAN gate that BUILD_PLAN calls the last one before strangers.

Selection is seeded (`SEED = 20260825`) and stratified: section A round-robins across verdict words, section B round-robins across the four playtime cohorts. Re-running the generator reproduces this exact sample.


## A. 3 verdicts to spot-check

- [ ] **Hollow Knight** (`367520`, flash-lite) - **Buy**
      refu 72.4% -> earl 93.2% -> mid 95.9% -> vete 97.0%
      > A sweeping underground adventure with stunning art and punishing combat.

- [ ] **Grand Theft Auto: San Andreas – The Definitive Edition** (`1547000`, flash-lite) - **Wait**
      refu 39.6% -> earl 81.8% -> mid 83.4% -> vete 85.2%
      > Classic chaos returned with rough edges and broken physics.

- [ ] **Hades** (`1145360`, flash-lite) - **Buy**
      refu 86.2% -> earl 95.9% -> mid 97.4% -> vete 100.0%
      > Stunning art and sharp action blend into an addictive loop.


## B. Twenty citations to audit for QR-4 (invariant 8)

Read each review text. Anything NSFW or slur-bearing blocks deploy.

 1. [ ] Grand Theft Auto: San Andreas – The Definitive Edition / mid / `231147873`
       claim: Reviewers report that airplane and helicopter controls feel awkward and require manual remapping to become pla
       text : Just finished game. Took me 54.7 hours. Yes, the remaster still has plenty of bugs that weren't in the original version - but there's noticeably fewer of them now compared to how it was at launch. What really bugged me though was the controls - I don't underst

 2. [ ] Hollow Knight / early / `230702735`
       claim: Reviewers describe the game as difficult, noting that bosses present a strong challenge.
       text : very fun. played for 30 minutes, then forgot about it. it lay there for 2 days then i came back. i fought false knight and the one at greenpath so far. game is very addicting and i love the artstyle. i feel like the game is a nice challenge and you really have

 3. [ ] Hades / veteran / `230859797`
       claim: Reviewers note that the final region features hazards such as poison spills and difficult-to-see projectiles, 
       text : [i]Very Good; but I question its S-Tier Status[/i] The difference between good and exceptional status in my opinion comes down to elements that can seem a bit nitpicky; but I think that is what holds Hades back from the highest accolades. First, I’d like to hi

 4. [ ] Hades / early / `231887461`
       claim: Reviewers note that dying in the game advances the story and character progression rather than feeling purely 
       text : The more I play this game, the more addicted I get: You fail a run, upgrade your stats with the items you collected, start a new run and get farther than before. Because you're able to progress the story after every run, failing doesn't feel punishing. On the 

 5. [ ] Grand Theft Auto: San Andreas – The Definitive Edition / refund_window / `217438837`
       claim: Reviewers report that physics, driving controls, and vehicle-handling mechanics feel worse than the original v
       text : Bad controls, bad driving, a lots of bug. They say this game was fixed, but its not. If you want to play this game, just get a PS2.

 6. [ ] Hades / early / `232414774`
       claim: Reviewers note that the game runs well on Linux and Steam Deck.
       text : I suck at it but it's very good. Always a big plus if games run this well on Linux.

 7. [ ] Hades / refund_window / `232281301`
       claim: Reviewers report that the game runs smoothly.
       text : Peak game played nice and smooth 10/10

 8. [ ] Grand Theft Auto: San Andreas – The Definitive Edition / mid / `230538528`
       claim: Reviewers note that the updated drawing distance significantly improves the game by preventing sudden object s
       text : As someone who spent most of my childhood practically living in San Andreas even spending years managing SA:MP servers back in the day. This is by far my favourite GTA of all time. I hold this game to an impossibly high standard. While the Definitive Edition d

 9. [ ] Hades / veteran / `229142051`
       claim: Reviewers report that the game incorporates story progression, dialogue updates, and character interactions in
       text : Hades is easily one of the best roguelike / hack and slash games I’ve ever played. What pulled me in first was the setting. I’ve always been interested in mythology, gods, divine powers, and stories built around them, so this game immediately caught my attenti

10. [ ] Hollow Knight / early / `230785026`
       claim: Reviewers note that the game's opening hours feel slow, boring, or take time to get into before picking up pac
       text : The first hour is more or less a strange introduction from what i remember, past that it's fun.,. [h2] HOWEVER... [/h2] I'm not going to pretend the game is perfect, even in the little time I've played it I've seen some issues. Sometimes, the shadow you leave 

11. [ ] Hades / refund_window / `231085638`
       claim: Reviewers praise the voice acting, music, and audio presentation.
       text : 1 hour in and already see the love which was put in for the game gameplay is fun, visuals are stunning, lightweight download, writing, voice acting and the lore all are great

12. [ ] Grand Theft Auto: San Andreas – The Definitive Edition / mid / `232036513`
       claim: Reviewers describe the Rockstar launcher as slow, requiring minutes to launch the game.
       text : In my opinion, this game is quite good, there may be some things that are still bothering me, for example, the launcher is very slow, I have to wait about than 1-3 minutes for the launch of this game, and some bugs that sometimes still bother me a little. Over

13. [ ] Grand Theft Auto: San Andreas – The Definitive Edition / mid / `232053415`
       claim: Reviewers experience random crashes and fatal Unreal Engine errors during gameplay and mission attempts.
       text : The story carried this version of game, the nostalgia. I came to realize that the replayability of this game's edition is 0, compared to the OG that i have finished countless of times. The first thing that came across to my issue was the Audio, some of it are 

14. [ ] Hades / early / `228862016`
       claim: Reviewers note that the game runs well on Linux and Steam Deck.
       text : I went into this not really knowing what it was, just that it was very well rated, those ratings are well deserved this is a very fun game. Love the art style, love the voice acting, love the game play. Works fine on my Debian 12 install as far as I can tell

15. [ ] Hades / veteran / `230235792`
       claim: Reviewers describe the narrative and dialogue continuing to progress and introduce new lines even after comple
       text : I love this game so much I decided to get every possible achievement. After more than 100 runs and getting the epilogue, it still had new lines of dialogues and contents! How crazy is that? I really wish we could be able to play Hades but multiplayer :')

16. [ ] Grand Theft Auto: San Andreas – The Definitive Edition / veteran / `221039151`
       claim: Reviewers describe encountering persistent bugs and glitches, including pedestrians panicking for no reason, j
       text : Even in 2026, after the Definitive Edition was finally 'fixed', this version of San Andreas is a massive pile of bugs and glitches that didn't exist in the OG version of the game. The Definitive Edition versions of GTA III and Vice City are largely fine at thi

17. [ ] Grand Theft Auto: San Andreas – The Definitive Edition / refund_window / `217434441`
       claim: Reviewers describe the color palette and lighting as unfaithful to the original release, citing an unwanted ye
       text : It has been a few years since it dropped and fixes have been made so I decided to give it a try. And I just cannot enjoy it, the visuals are just far from the original vision and feel of the original game, the warm sunset and lush colors are gone.... I got to 

18. [ ] Grand Theft Auto: San Andreas – The Definitive Edition / refund_window / `224167218`
       claim: Reviewers state that original versions of the game were removed from the Steam store.
       text : I prefered the old school version, the definitive version is buggy, the characters look bizarre especially Rider, controls are not quite good and some missions you required to take items are not present so you need to restart it quite annoying. My recommandati

19. [ ] Grand Theft Auto: San Andreas – The Definitive Edition / mid / `231102676`
       claim: Reviewers experience random crashes and fatal Unreal Engine errors during gameplay and mission attempts.
       text : UE4 Fatal Error renders the game unplayable due to crashes that occur after any save is made, even the auto saves generated by the game itself. The solution is to roll back to a save that works... unless that save also decides to stop working, despite already 

20. [ ] Hades / veteran / `229645039`
       claim: Reviewers describe the combat and movement as fast-paced and advise playing with a controller rather than a mo
       text : Holy crap, what a fun game! I've played other roguelikes or roguelites, and many are fun, but you wouldn't think a strong story is one of their strengths. In the case of Hades: story, voice acting, dialogue are all very strong points of the game. And of course


## Result

- [ ] QR-4: all 20 citations clean (any failure blocks deploy)
- [ ] Verdicts: all 3 read as defensible against their split

Notes:
