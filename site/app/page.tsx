import { catalog } from "../lib/catalog";
import { Home } from "../components/Home";

export default async function Page() {
  return <Home entries={await catalog()} />;
}
