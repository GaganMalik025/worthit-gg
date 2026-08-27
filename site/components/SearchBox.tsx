"use client";

/**
 * Selection-only typeahead over the static index.
 *
 * There is no free-text submit path: Enter with nothing highlighted does
 * nothing, and there is no way to send a string that is not an index entry.
 * That is what lets a cache miss carry a resolved appid straight into
 * generation or the queue, with no disambiguation step.
 *
 * Both shards start loading on first focus, in the same tick - core resolves
 * first so the box is usable immediately, and the tail follows so a tail-only
 * query still resolves without a visible stall. Nothing is fetched for users
 * who never touch the box.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CAPSULE, createIndexLoader, search, type Hit } from "../lib/search";
import { capture } from "../lib/analytics";

export function SearchBox({
  haveVerdict,
  verdictWord,
  onSelect,
}: {
  haveVerdict: (appid: number) => boolean;
  verdictWord: (appid: number) => string | null;
  onSelect: (hit: Hit) => void;
}) {
  const loader = useMemo(() => createIndexLoader(), []);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [active, setActive] = useState(-1);
  const [open, setOpen] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      const res = search(loader.shards(), query);
      setHits(res);
      setActive(res.length ? 0 : -1);
      setOpen(res.length > 0);
      // Inside the debounce on purpose: one event per SETTLED query, not one
      // per keystroke. LENGTH ONLY - never the string. What someone types into
      // a search box is theirs, and a game title is enough to identify a person
      // when it is rare enough; the length still answers the question this
      // event exists for (are people searching at all, and giving up part-way).
      if (query.length > 0) capture("search", { query_length: query.length });
    }, 120);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [query, loader]);

  const choose = useCallback(
    (hit: Hit | undefined) => {
      if (!hit) return; // Enter with no highlighted option does nothing
      setOpen(false);
      onSelect(hit);
    },
    [onSelect],
  );

  return (
    <div className="searchbox">
      <input
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-controls="search-results"
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `opt-${hits[active]?.appid}` : undefined}
        placeholder="Search a game…"
        value={query}
        onFocus={() => loader.start()}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((i) => Math.min(i + 1, hits.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((i) => Math.max(i - 1, 0));
          } else if (e.key === "Enter") {
            e.preventDefault();
            choose(hits[active]);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />

      {open && (
        <ul id="search-results" role="listbox" className="results">
          {hits.map((h, i) => {
            const word = verdictWord(h.appid);
            return (
              <li
                key={h.appid}
                id={`opt-${h.appid}`}
                role="option"
                aria-selected={i === active}
                className={i === active ? "row active" : "row"}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(h);
                }}
              >
                {/* capsule left, title right */}
                <img
                  className="capsule"
                  src={CAPSULE(h.appid, loader.art)}
                  alt=""
                  aria-hidden="true"
                  loading="lazy"
                  onError={(e) => {
                    (e.currentTarget as HTMLImageElement).style.visibility = "hidden";
                  }}
                />
                <span className="title">{h.title}</span>
                {haveVerdict(h.appid) && word ? (
                  <span className={`chip ${word.toLowerCase()}`}>{word}</span>
                ) : (
                  <span className="chip none mono">not yet</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
