/** Build-time loader for public/genres.json. Server-only: it reads the disk. */
import { readFile } from "node:fs/promises";
import path from "node:path";
import type { Genres } from "./genres";

const EMPTY: Genres = { sections: [], members: {} };

/** Missing or unreadable genres.json renders a home page with no sections rather
 *  than failing the build: the header and search still work. */
export async function loadGenres(): Promise<Genres> {
  try {
    const raw = JSON.parse(
      await readFile(path.join(process.cwd(), "public/genres.json"), "utf-8"),
    );
    return { sections: raw.sections ?? [], members: raw.members ?? {} };
  } catch {
    return EMPTY;
  }
}
