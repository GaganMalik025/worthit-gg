import { catalog } from "../lib/catalog";
import { homeSections } from "../lib/genres";
import { loadGenres } from "../lib/genres.server";
import { Home } from "../components/Home";

export default async function Page() {
  const entries = await catalog();
  return <Home entries={entries} sections={homeSections(entries, await loadGenres())} />;
}
