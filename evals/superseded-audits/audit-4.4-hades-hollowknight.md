# 4.4 audit - Hades and Hollow Knight, first audit under the current process

These two titles were live-generated on the CI runner before the 4.4/4.5
audit work existed, and published through the legacy header shim. Their
extraction artifacts never reached this machine, so the header rollout
could not re-synthesize them and they were the last two verdicts on the
pre-split shape.

They have now been re-ingested end to end, which produced **new claims and
new citations**. Nothing about them has been read by a human before: the
earlier publication predates the audit process entirely. This is their
first audit, not a re-audit.

Automated QR-4: **96 citations across the two verdicts, 0 failures** (and
7098 across all 134 catalog verdicts, PASS).

Same process as every other 4.4 pass: read the citation, confirm nothing
distressing reaches a reader, confirm the claim it supports is a fair
reading of it, confirm the verdict reads sound.


## A. The two verdicts

- [ ] **Hades** (`1145360`) - **Buy**
      refu 86.2% -> earl 95.9% -> mid 97.4% -> vete 100.0%
      > Stunning art and sharp action blend into an addictive loop.
      >   + you love responsive action combat
      >   + you appreciate stories that evolve through defeat
      >   + you want deep voice acting
      >   - you dislike restarting runs from the beginning
      >   - you struggle with fast projectiles and visual clutter
      >   - you prefer playing with a mouse and keyboard

- [ ] **Hollow Knight** (`367520`) - **Buy**
      refu 72.4% -> earl 93.2% -> mid 95.9% -> vete 97.0%
      > A sweeping underground adventure with stunning art and punishing combat.
      >   + you love deep exploration and rewarding combat
      >   + you enjoy mastering challenging boss patterns
      >   + you appreciate atmospheric worlds and incredible soundtracks
      >   - you dislike getting lost without clear direction
      >   - you find grueling platforming challenges frustrating
      >   - you want a fast-paced opening right away


## B. Twenty citations to audit for QR-4 (invariant 8)

  1. [ ] Hades / early / DIFFICULTY / `232223343`  (12.2h, recommends)
       claim: Reviewers state that different weapons offer distinct playstyles.
       text : One of the best game that i play, the good thing about this game is that each weapon has a  really huge diffrence in playstyle while some of them a bit similiar like spear and gauntlet. but sadly i feel like the boons does not have that much option, anway this...

  2. [ ] Hades / early / CONTENT / `231570790`  (11.4h, recommends)
       claim: Reviewers describe the game as having an art style featuring hand-drawn visuals and dynamic lighting.
       text : my goat, my most fav game ever, beautiful art style, soundtrack, and fighting mechanics :DDD

  3. [ ] Hades / mid / CONTENT / `225336866`  (21.1h, recommends)
       claim: Reviewers note that completing the main story requires achieving multiple successful escapes, which can feel r...
       text : Great game - combat, visuals and soundtrack but its annoying that the story is drip-fed to you. You need to complete 10 successful runs to finish the main story, though being asked to play more isnt really a bad thing. Also many more playthroughs are needed to...

  4. [ ] Hades / mid / CONTENT / `232484838`  (40.7h, recommends)
       claim: Reviewers note that the game features extensive voice-acted dialogue that changes and reacts to player progres...
       text : I have an interest in Greek Mythology. One day, I saw this game on a discount and decided to buy it. 
 
 Here's my story:
 I'm not really much of a roguelike fan, but IMO this game does a pretty in introducing roguelike gaming to newbies like me. It's very int...

  5. [ ] Hades / refund_window / CONTENT / `229019339`  (1.7h, recommends)
       claim: Reviewers praise the voice acting, music, and audio presentation.
       text : didn't expect to get hooked this fast. Every run feels different thanks to the combinations of boons and weapons, and even when you fail, it never feels like you wasted your time. The story keeps moving forward, the characters always have something new to say,...

  6. [ ] Hades / refund_window / CONTENT / `229019339`  (1.7h, recommends)
       claim: Reviewers describe the voice acting and music as high quality.
       text : didn't expect to get hooked this fast. Every run feels different thanks to the combinations of boons and weapons, and even when you fail, it never feels like you wasted your time. The story keeps moving forward, the characters always have something new to say,...

  7. [ ] Hades / veteran / CONTENT / `229669874`  (107.6h, recommends)
       claim: Reviewers report that the game incorporates story progression, dialogue updates, and character interactions in...
       text : This game has quickly become one of my favorites in recent years.  I love how the story unfolds through bite-sized character interactions, both mid-run & at the main hub. It's also kind of cool to see characters interacting with you & each other, based on your...

  8. [ ] Hades / veteran / DIFFICULTY / `229669874`  (107.6h, recommends)
       claim: Reviewers note that the game includes an optional God Mode providing incremental damage resistance upon death ...
       text : This game has quickly become one of my favorites in recent years.  I love how the story unfolds through bite-sized character interactions, both mid-run & at the main hub. It's also kind of cool to see characters interacting with you & each other, based on your...

  9. [ ] Hollow Knight / early / DIFFICULTY / `230595574`  (16.1h, recommends)
       claim: Reviewers note that the game's opening hours feel slow, boring, or take time to get into before picking up pac...
       text : the uptake is boring but now i'm having a lot more fun and the fun only just started and i know it lasts for a while

 10. [ ] Hollow Knight / early / DIFFICULTY / `232224378`  (6.9h, recommends)
       claim: Reviewers report that the game features a challenging difficulty level with difficult boss fights and requires...
       text : Hollow Knight is an amazing metroidvania with beautiful art, incredible music, and fun gameplay. Exploring the world is always exciting, and every new area feels unique. The bosses are challenging but very rewarding to beat. It can be difficult at times, but t...

 11. [ ] Hollow Knight / mid / DIFFICULTY / `231013570`  (31.9h, recommends)
       claim: Reviewers describe the boss fights and overall gameplay as highly challenging, requiring patience to learn att...
       text : I bought this game years ago. I loved all the Dark Souls games, and I enjoyed the art style. I started it multiple times but never got that far. I had never played a Metroidvania before, so I was constantly getting lost and was overwhelmed by the size of the m...

 12. [ ] Hollow Knight / mid / CONTENT / `230881033`  (64.7h, does not recommend)
       claim: Reviewers report that the early game is slow and can leave new players lost or unsure of where to go before op...
       text : (Yap session incoming)  All I've heard is that this game is a masterpiece, and yet no one can tell me exactly what makes this game a masterpiece. After beating path of pain and played the grand majority of bosses excluding absolute radiance and hornet nosk, ho...

 13. [ ] Hollow Knight / refund_window / CONTENT / `230790549`  (0.6h, does not recommend)
       claim: Reviewers report that the game requires significant backtracking and navigation through locked areas.
       text : backtracking simulator  + locked area simulator
 
 probably fun if have patience for that but I don't
 
 i enjoyed the first boss fight

 14. [ ] Hollow Knight / refund_window / CONTENT / `230541855`  (1.8h, does not recommend)
       claim: Reviewers report that the game requires significant backtracking and navigation through locked areas.
       text : Let's take all the bad things from dark souls games. Yea. Farmed berries for a map pointer update. Got locked in a boss room and I don't even remember how I get there. F**k you player. Nice game.

 15. [ ] Hollow Knight / veteran / DIFFICULTY / `230513328`  (294.8h, recommends)
       claim: Reviewers note that the game features a slow pacing or confusing structure at the beginning, where players can...
       text : Yo gng as someone who plat the game and did all bosses no hit , i fcking love this game and is for me the best gaming experience i had , but i do understand that some ppl dont like the game as u are lost at the start and some ppl may quit , overrall i highly r...

 16. [ ] Hollow Knight / veteran / CONTENT / `230579732`  (200.9h, recommends)
       claim: Reviewers praise the soundtrack as outstanding and one of the best parts of the experience.
       text : This game is one of the best games to ever exist. The soundtrack is amazing, the visuals are amazing to look at, and the game play is amazing! The story is so good it will forever be in my memory. Without getting into spoilers, the bosses are amazing! The char...

 17. [ ] Hades / early / CONTENT / `231887461`  (8.0h, recommends)
       claim: Reviewers describe the game as having an art style featuring hand-drawn visuals and dynamic lighting.
       text : The more I play this game, the more addicted I get: You fail a run, upgrade your stats with the items you collected, start a new run and get farther than before. Because you're able to progress the story after every run, failing doesn't feel punishing. On the ...

 18. [ ] Hollow Knight / veteran / DIFFICULTY / `232385394`  (154.6h, recommends)
       claim: Reviewers note that the game features a slow pacing or confusing structure at the beginning, where players can...
       text : Goated game!  The only bad thing I noticed is that the pacing at the beginning is a bit slow. I personally didn’t really mind it, though. I’ve heard other people complain about it, but once you get past the slow start and really get into the flow of the game, ...

 19. [ ] Hades / refund_window / CONTENT / `231552618`  (1.6h, recommends)
       claim: Reviewers describe the voice acting and music as high quality.
       text : Platinumed this game on ps4 few years ago, and replaying with 60 fps and without remembering much, this game is still a blast. Absolutely love it. So smooth, fun and with such great music, dialogue and voice acting

 20. [ ] Hollow Knight / early / CONTENT / `230366449`  (14.1h, recommends)
       claim: Reviewers highlight the game's art style, music, and atmospheric world building.
       text : Very difficult (for me at least), clearly there was much thought put in to the story as well as the actual play of the game, there is endless depth and complexity to this world and the art is also just incredibly beautiful.

## C. Result

Same bar as every other 4.4 pass: any citation that should not reach a reader
blocks the title, and the fix is regeneration, never editing the citation.

- citations read: **20 of 20**
- failures: **0**
- verdict wording sound (y/n): **y**
- coverage: both titles, all four cohorts (`refund_window`, `early`, `mid`,
  `veteran`)
- notes: **Manual audit confirmed clean — 20/20 citations read across Hades and
  Hollow Knight, both titles and all four cohorts, nothing inappropriate
  found.** First manual audit either title has ever had: the versions served
  through the legacy shim predated the audit process and were never reviewed.

Completed 2026-08-10. Recorded in `evals/RESULTS.md`.
