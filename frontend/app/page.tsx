import { AuthScreen } from "./components/auth-screen";
import { getPublicApiUrl } from "./lib/env";

export default function Home() {
  return <AuthScreen apiUrl={getPublicApiUrl()} />;
}
