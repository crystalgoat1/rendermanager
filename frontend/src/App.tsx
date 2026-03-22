import type { JSX } from "preact";
import { lazy, Suspense } from "preact/compat";
import { Route, Switch, Redirect, useLocation } from "wouter";
import { useSession } from "./hooks/useSession";
import { AppLayout } from "./components/AppLayout";
import { InfoTooltipProvider } from "./components/InfoTooltipContext";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";

// Lazy-load protected pages for smaller initial bundle (faster mobile login)
const DashboardPage = lazy(() => import("./pages/DashboardPage").then(m => ({ default: m.DashboardPage })));
const NewJobPage = lazy(() => import("./pages/NewJobPage").then(m => ({ default: m.NewJobPage })));
const EditJobPage = lazy(() => import("./pages/EditJobPage").then(m => ({ default: m.EditJobPage })));
const HistoryPage = lazy(() => import("./pages/HistoryPage").then(m => ({ default: m.HistoryPage })));
const AgentSetupPage = lazy(() => import("./pages/AgentSetupPage").then(m => ({ default: m.AgentSetupPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then(m => ({ default: m.SettingsPage })));
const DownloadPage = lazy(() => import("./pages/DownloadPage").then(m => ({ default: m.DownloadPage })));
const HelpPage = lazy(() => import("./pages/HelpPage").then(m => ({ default: m.HelpPage })));
const PrivacyPolicyPage = lazy(() => import("./pages/legal/PrivacyPolicyPage").catch(() => import("./pages/HomePage").then(m => ({ default: m.HomePage }))).then(m => ({ default: m.default || m })));
const TermsOfServicePage = lazy(() => import("./pages/legal/TermsOfServicePage").catch(() => import("./pages/HomePage").then(m => ({ default: m.HomePage }))).then(m => ({ default: m.default || m })));

const PageLoader = () => (
  <div className="flex items-center justify-center min-h-screen bg-bg-base text-slate-500 text-sm">Loading...</div>
);

function ProtectedRoute({ component: Component }: { component: () => JSX.Element }) {
  const { session, loading } = useSession();
  const [location] = useLocation();
  if (loading) return <PageLoader />;
  if (!session) return <Redirect to={`/login?next=${encodeURIComponent(location)}`} />;
  return (
    <AppLayout>
      <Suspense fallback={<PageLoader />}>
        <Component />
      </Suspense>
    </AppLayout>
  );
}

// Separate component so we can use hooks and pass params
function EditJobRoute({ jobId }: { jobId: string }) {
  const { session, loading } = useSession();
  const [location] = useLocation();
  if (loading) return <PageLoader />;
  if (!session) return <Redirect to={`/login?next=${encodeURIComponent(location)}`} />;
  return (
    <AppLayout>
      <Suspense fallback={<PageLoader />}>
        <EditJobPage jobId={jobId} />
      </Suspense>
    </AppLayout>
  );
}

export function App() {
  return (
    <InfoTooltipProvider>
    <Switch>
      <Route path="/login" component={LoginPage} />
      <Route path="/agent-setup">
        {() => (
          <Suspense fallback={<PageLoader />}>
            <AgentSetupPage />
          </Suspense>
        )}
      </Route>
      <Route path="/download">
        {() => <ProtectedRoute component={DownloadPage} />}
      </Route>
      <Route path="/dashboard">
        {() => <ProtectedRoute component={DashboardPage} />}
      </Route>
      <Route path="/new">
        {() => <ProtectedRoute component={NewJobPage} />}
      </Route>
      <Route path="/edit/:jobId">
        {(params: { jobId?: string } | null) => <EditJobRoute jobId={params?.jobId ?? ""} />}
      </Route>
      <Route path="/history">
        {() => <ProtectedRoute component={HistoryPage} />}
      </Route>
      <Route path="/settings">
        {() => <ProtectedRoute component={SettingsPage} />}
      </Route>
      <Route path="/help">
        {() => <ProtectedRoute component={HelpPage} />}
      </Route>
      <Route path="/legal/privacy">
        {() => (
          <Suspense fallback={<PageLoader />}>
            <PrivacyPolicyPage />
          </Suspense>
        )}
      </Route>
      <Route path="/legal/terms">
        {() => (
          <Suspense fallback={<PageLoader />}>
            <TermsOfServicePage />
          </Suspense>
        )}
      </Route>
      <Route path="/">
        {() => {
          const { session, loading } = useSession();
          // Show homepage immediately — don't block on session check.
          // Once session resolves, redirect logged-in users to dashboard.
          if (!loading && session) return <Redirect to="/dashboard" />;
          return <HomePage />;
        }}
      </Route>
    </Switch>
    </InfoTooltipProvider>
  );
}
