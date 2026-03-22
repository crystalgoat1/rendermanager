import { Link } from "wouter";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { APP_DISPLAY_NAME } from "../brand";

const STEPS = [
  {
    num: "01",
    icon: "install_desktop",
    title: "Install the app on your render PC",
    desc: "A lightweight app connects your Blender installation to your account. It watches a local Blend Files folder on your machine.",
  },
  {
    num: "02",
    icon: "rocket_launch",
    title: "Submit renders from anywhere",
    desc: "Drop .blend files into your workspace folder, then start renders from the web dashboard, your phone, or the Blender addon. Rendering happens locally on your PC in the background.",
  },
  {
    num: "03",
    icon: "visibility",
    title: "Monitor live from any device",
    desc: "Watch frames appear in real time, switch EXR render passes, pause or cancel. All from any browser. Your files never leave your machine.",
  },
];

const FEATURES = [
  {
    icon: "tune",
    title: "Remote render control",
    desc: "Queue up render jobs, change settings, pause, resume, or cancel from anywhere.",
  },
  {
    icon: "image",
    title: "Live frame previews",
    desc: "Watch your render progress frame by frame from any browser or phone.",
  },
  {
    icon: "layers",
    title: "EXR pass viewer",
    desc: "Browse individual render passes from multilayer EXR outputs directly in your browser.",
  },
  {
    icon: "devices",
    title: "Multi-device access",
    desc: "Control renders from your phone, tablet, or any computer with a browser.",
  },
];

export function HomePage() {
  return (
    <div className="bg-bg-base text-slate-200 font-display min-h-screen">

      {/* Nav */}
      <nav className="sticky top-0 z-50 flex items-center justify-between px-6 lg:px-12 py-4 bg-bg-base/80 backdrop-blur-md border-b border-white/5">
        <div className="flex items-center gap-2">
          <Logo size="lg" className="hidden sm:flex" />
          <Logo size="md" className="flex sm:hidden" />
        </div>
        <Link href="/login" className="px-5 py-2 text-sm font-semibold border border-slate-700 rounded-lg hover:bg-slate-800 transition-colors inline-block text-center cursor-pointer">
          Sign In
        </Link>
      </nav>

      {/* Hero */}
      <header className="relative px-6 lg:px-12 pt-24 pb-28 text-center overflow-hidden">
        {/* Smooth ambient glow using radial-gradient instead of blurred divs to prevent banding */}
        <div
          className="absolute inset-0 pointer-events-none opacity-15"
          style={{
            background: "radial-gradient(ellipse 60% 50% at 20% 30%, #6366f1, transparent), radial-gradient(ellipse 50% 40% at 80% 70%, #0ea5e9, transparent)",
          }}
        />
        <div className="relative z-10 max-w-2xl mx-auto">
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold leading-[1.1] tracking-tight text-white mb-6">
            Control your Blender renders from{" "}
            <span className="text-gradient">any device</span>
          </h1>
          <p className="text-lg text-slate-400 mb-10 leading-relaxed max-w-lg mx-auto">
            A small app runs on your PC alongside Blender. Start renders, track progress with live frame previews, and manage everything from your phone or any browser. Your own hardware does the work.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link href="/login" className="px-8 py-4 gradient-primary text-white font-bold rounded-xl shadow-lg shadow-black/20 active:scale-[0.98] transition-transform text-lg inline-block cursor-pointer">
              Get Started Free
            </Link>
          </div>
          <p className="mt-4 text-xs text-slate-500">No credit card required</p>
        </div>
      </header>

      {/* How it works */}
      <section className="px-6 lg:px-12 py-24 bg-bg-surface">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-2xl md:text-3xl font-bold text-white mb-3">How it works</h2>
            <div className="w-12 h-1 gradient-primary mx-auto rounded-full" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {STEPS.map(({ num, icon, title, desc }) => (
              <div
                key={num}
                className="flex flex-col p-6 rounded-xl bg-bg-base border border-white/5 hover:border-primary/20 transition-colors relative overflow-hidden"
              >
                <div className="absolute -right-4 -top-4 w-24 h-24 bg-primary/5 rounded-full blur-2xl" />
                <div className="flex items-center justify-between mb-4 relative z-10">
                  <span className="text-4xl font-black text-gradient opacity-80">{num}</span>
                  <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center">
                    <Icon name={icon} className="text-primary text-2xl" />
                  </div>
                </div>
                <h3 className="text-base font-bold text-white mb-2 relative z-10">{title}</h3>
                <p className="text-slate-400 text-sm leading-relaxed relative z-10">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="px-6 lg:px-12 py-24 bg-bg-base">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-2xl md:text-3xl font-bold text-white mb-3">Features</h2>
            <div className="w-12 h-1 gradient-primary mx-auto rounded-full" />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {FEATURES.map(({ icon, title, desc }) => (
              <div
                key={title}
                className="flex flex-col p-6 rounded-xl bg-bg-surface border border-white/5 hover:border-primary/20 transition-colors"
              >
                <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center mb-4">
                  <Icon name={icon} className="text-primary text-2xl" />
                </div>
                <h3 className="text-base font-bold text-white mb-2">{title}</h3>
                <p className="text-slate-400 text-sm leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="px-6 lg:px-12 py-24 bg-bg-surface">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-2xl md:text-3xl font-bold text-white mb-3">Simple pricing</h2>
            <p className="text-slate-400 text-sm">Start free, upgrade when you need more.</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Free */}
            <div className="p-8 rounded-xl bg-bg-base border border-white/5">
              <h3 className="text-xl font-bold text-white mb-2">Free</h3>
              <div className="flex items-baseline gap-1 mb-6">
                <span className="text-4xl font-bold text-white">Free</span>
              </div>
              <ul className="space-y-3 mb-8">
                {["1 computer", "1 active render job", "Live frame previews", "VRAM recovery"].map(f => (
                  <li key={f} className="flex items-center gap-3 text-sm text-slate-200">
                    <Icon name="check_circle" className="text-primary text-lg shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
              <Link href="/login" className="w-full py-3 border border-slate-700 text-white font-bold rounded-lg hover:bg-slate-800 transition-colors block text-center cursor-pointer">
                Get Started
              </Link>
            </div>
            {/* Pro */}
            <div className="p-8 rounded-xl bg-bg-base border-2 border-primary/50 glow-border relative overflow-hidden">
              <div className="absolute top-0 right-0 gradient-primary text-white text-[10px] font-bold px-3 py-1 rounded-bl-lg tracking-widest uppercase">
                Pro
              </div>
              <h3 className="text-xl font-bold text-white mb-2">Pro</h3>
              <div className="flex items-baseline gap-1 mb-6">
                <span className="text-4xl font-bold text-white">9</span>
                <span className="text-slate-400">/mo</span>
              </div>
              <ul className="space-y-3 mb-8">
                {["Up to 3 computers", "8 queued jobs per computer", "Frame browsing & animation preview", "Advanced render settings"].map(f => (
                  <li key={f} className="flex items-center gap-3 text-sm font-medium text-white">
                    <Icon name="check_circle" className="text-primary text-lg shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>
              <Link href="/login?next=/settings?upgrade=true" className="w-full py-4 gradient-primary text-white font-bold rounded-lg shadow-lg shadow-black/20 active:scale-[0.98] transition-transform block text-center cursor-pointer">
                Upgrade to Pro
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="px-6 lg:px-12 py-20 bg-primary/5 border-t border-white/5">
        <div className="max-w-2xl mx-auto text-center">
          <h2 className="text-2xl md:text-3xl font-bold text-white mb-4">Ready to try it?</h2>
          <p className="text-slate-400 mb-8 text-sm">Set up takes less than a minute. Start monitoring your renders today.</p>
          <Link href="/login" className="px-10 py-4 gradient-primary text-white font-bold rounded-xl shadow-lg shadow-black/20 active:scale-[0.98] transition-transform text-lg inline-block cursor-pointer">
            Create Free Account
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-6 lg:px-12 py-10 text-center border-t border-white/5">
        <div className="flex items-center justify-center mb-4 opacity-80">
          <Logo size="md" />
        </div>
        <div className="flex justify-center gap-6 mb-4 text-xs font-medium text-slate-400">
          <a href="/legal/terms" className="hover:text-white transition-colors">
            Terms of Service
          </a>
          <a href="/legal/privacy" className="hover:text-white transition-colors">
            Privacy Policy
          </a>
          <a href="mailto:support@rendermanager.com" className="hover:text-white transition-colors">
            Contact
          </a>
        </div>
        <p className="text-[10px] text-slate-500 font-medium uppercase tracking-widest">
          © {new Date().getFullYear()} {APP_DISPLAY_NAME}
        </p>
      </footer>
    </div>
  );
}
