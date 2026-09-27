import { Loading } from "../components/ui/alert";
import { useFocusHeading, useHashRoute } from "../lib/router";
import { DashboardPage } from "../pages/dashboard";
import { ReportsPage } from "../pages/reports";
import { RolesPage } from "../pages/roles";
import { SelfReportPage } from "../pages/self-report";
import { AppShell } from "./shell";
import { useSession } from "./session";
import { SignIn } from "./sign-in";

export function App() {
  const { session, checking } = useSession();

  if (checking) {
    return (
      <main id="main" className="flex min-h-dvh items-center justify-center p-6">
        <Loading label="Checking your session\u2026" />
      </main>
    );
  }

  // No session is the ordinary signed-out state, so it gets the login rather
  // than an error page.
  if (session === null) return <SignIn />;

  return (
    <AppShell>
      <Routes />
    </AppShell>
  );
}

function Routes() {
  const path = useHashRoute();
  useFocusHeading(path);
  switch (path) {
    case "/roles":
      return <RolesPage />;
    case "/reports":
      return <ReportsPage />;
    case "/self-report":
      return <SelfReportPage />;
    default:
      return <DashboardPage />;
  }
}
