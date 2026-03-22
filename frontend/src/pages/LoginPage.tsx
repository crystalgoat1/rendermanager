import { useState } from "preact/hooks";
import { supabase } from "../supabaseClient";
import { Logo } from "../components/Logo";
import { APP_DISPLAY_NAME } from "../brand";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // After login, redirect to the `next` param (e.g. /agent-setup) or /dashboard
  // Validate: only allow relative paths starting with / to prevent open redirects
  const rawNext = new URLSearchParams(window.location.search).get("next");
  const safeNext = rawNext && rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : null;
  const redirectTarget = safeNext
    ? `${window.location.origin}${safeNext}`
    : `${window.location.origin}/dashboard`;

  async function handleEmailAuth(e: Event) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (isSignUp) {
        const { error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        setError("Check your email for a confirmation link.");
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        // Redirect to the original page or dashboard
        window.location.href = redirectTarget;
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleGoogleLogin() {
    setLoading(true);
    setError(null);
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: redirectTarget },
      });
      if (error) throw error;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Google login failed");
      setLoading(false);
    }
  }

  const isInfo = !!error && error.toLowerCase().includes("check");

  return (
    <div className="min-h-screen bg-bg-base flex items-center justify-center p-6 font-display">
      {/* Ambient glow */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-primary/20 rounded-full blur-[120px] opacity-40" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-secondary/20 rounded-full blur-[100px] opacity-30" />
      </div>

      <div className="relative z-10 w-full max-w-[380px]">
        {/* Logo */}
        <div className="text-center mb-8">
          <Logo size="xl" className="justify-center mb-4" />
          <h1 className="sr-only">{APP_DISPLAY_NAME}</h1>
          <p className="text-slate-400 text-sm mt-1">
            {isSignUp ? "Create your account" : "Sign in to monitor your renders"}
          </p>
        </div>

        <div className="bg-bg-surface rounded-2xl p-6 border border-white/5 shadow-2xl">
          {/* Banner */}
          {error && (
            <div className={`mb-5 p-3 rounded-xl text-sm border ${isInfo
              ? "bg-primary/10 border-primary/20 text-primary"
              : "bg-red-500/10 border-red-500/20 text-red-400"
              }`}>
              {error}
            </div>
          )}

          {/* Google */}
          <button
            onClick={handleGoogleLogin}
            disabled={loading}
            className="w-full flex items-center justify-center gap-3 py-3 bg-white text-gray-800 rounded-xl font-semibold text-sm mb-5 hover:bg-gray-100 transition-colors disabled:opacity-60 shadow-sm"
          >
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
              <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" />
              <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" />
              <path fill="#FBBC05" d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" />
              <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" />
            </svg>
            Continue with Google
          </button>

          {/* Divider */}
          <div className="flex items-center gap-3 mb-5 text-slate-500 text-sm">
            <div className="flex-1 h-px bg-white/5" />
            or
            <div className="flex-1 h-px bg-white/5" />
          </div>

          {/* Email / password */}
          <form onSubmit={handleEmailAuth} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5 uppercase tracking-wider">
                Email
              </label>
              <input
                className="w-full bg-bg-base border border-white/10 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-primary/50"
                type="email"
                value={email}
                onInput={(e) => setEmail((e.target as HTMLInputElement).value)}
                placeholder="you@example.com"
                required
                autoComplete="email"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5 uppercase tracking-wider">
                Password
              </label>
              <input
                className="w-full bg-bg-base border border-white/10 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-primary/50"
                type="password"
                value={password}
                onInput={(e) => setPassword((e.target as HTMLInputElement).value)}
                placeholder={isSignUp ? "Choose a password" : "Your password"}
                required
                autoComplete={isSignUp ? "new-password" : "current-password"}
              />
            </div>
            {isSignUp && (
              <div className="flex items-start gap-2 pt-1 pb-2">
                <input
                  type="checkbox"
                  id="tos"
                  className="mt-1 h-4 w-4 rounded border-white/10 bg-bg-base text-primary focus:ring-primary/50"
                  required
                />
                <label htmlFor="tos" className="text-xs text-slate-400">
                  I agree to the{" "}
                  <a href="/legal/terms" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                    Terms of Service
                  </a>{" "}
                  and{" "}
                  <a href="/legal/privacy" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                    Privacy Policy
                  </a>
                  .
                </label>
              </div>
            )}
            <button
              type="submit"
              disabled={loading}
              className="w-full gradient-primary text-white font-bold py-3.5 rounded-xl shadow-lg shadow-black/20 active:scale-[0.98] transition-transform disabled:opacity-60"
            >
              {loading ? "Please wait..." : isSignUp ? "Create Account" : "Sign In"}
            </button>
          </form>

          <p className="text-center text-sm text-slate-500 mt-5">
            {isSignUp ? "Already have an account?" : "Don't have an account?"}{" "}
            <button
              className="text-primary font-semibold hover:text-primary/80 transition-colors"
              onClick={() => { setIsSignUp(!isSignUp); setError(null); }}
            >
              {isSignUp ? "Sign in" : "Sign up"}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
