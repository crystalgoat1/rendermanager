import { Link } from "wouter";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { APP_DISPLAY_NAME, APP_GITHUB_URL } from "../brand";

const STEPS = [
  {
    num: "01",
    icon: "download_for_offline",
    title: "Download & Install",
    desc: "Click the button above, run the installer, and follow the prompts. It takes under a minute.",
  },
  {
    num: "02",
    icon: "login",
    title: "Sign In",
    desc: `After installing, a setup window will appear. Point it to your Blender installation, then sign in with your ${APP_DISPLAY_NAME} account.`,
  },
  {
    num: "03",
    icon: "check_circle",
    title: "Start Rendering",
    desc: "The app is now running in your system tray and watching your Blend Files folder. Submit a render from the web dashboard or the Blender addon. It launches Blender in the background on your PC and streams progress live.",
  },
];

const FAQS = [
  {
    q: "What do I need before starting?",
    a: `Windows 10 or 11, Blender 4.0 or newer installed on your PC, and a ${APP_DISPLAY_NAME} account.`,
  },
  {
    q: "Where does the app run?",
    a: "It runs quietly in your system tray. You can click its icon anytime to pause, resume, or check on your renders.",
  },
  {
    q: "Can I use multiple PCs?",
    a: "Yes. Install the app on each machine and sign in. Each one registers automatically and can pick up jobs.",
  },
  {
    q: "How does the rendering work?",
    a: "When you submit a job, the app launches a separate Blender process in the background on your PC. Your open Blender stays untouched. Frames are saved locally and previews are streamed to the dashboard.",
  },
  {
    q: "Is my data safe?",
    a: "Your .blend files are only processed locally on your own machine. The app streams preview images and never uploads your project files.",
  },
  {
    q: "Can I inspect the source code?",
    a: "Yes. The agent is open source. You can review the full codebase on GitHub before installing.",
  },
];

export function DownloadPage() {
  return (
    <div className="flex flex-col min-h-screen bg-bg-base">
      {/* Page header */}
      <header className="sticky top-0 z-20 bg-bg-base/90 backdrop-blur-md border-b border-white/5 px-6 py-4 flex items-center gap-4">
        <Link href="/dashboard">
          <button className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/5 transition-colors">
            <Icon name="arrow_back" className="text-xl" />
          </button>
        </Link>
        <h1 className="text-xl font-bold tracking-tight">Download App</h1>
      </header>

      <main className="flex-1 p-6 pb-8">
        <div className="max-w-4xl mx-auto">

          {/* Hero section */}
          <div className="text-center mb-12">
            <Logo size="xl" className="justify-center mb-6" />
            <h2 className="sr-only">Set Up {APP_DISPLAY_NAME}</h2>
            <p className="text-slate-400 text-lg max-w-lg mx-auto">
              Install the app on your render PC. It connects Blender to your account so you can start, monitor, and control renders from anywhere. Your PC does the rendering locally.
            </p>
          </div>

          {/* Download button */}
          <div className="flex flex-col items-center mb-16">
            <a
              href="/installer/RenderManagerSetup.exe"
              download
              className="inline-flex items-center gap-3 gradient-primary hover:opacity-90 text-white font-bold py-4 px-10 rounded-xl shadow-xl shadow-black/20 transition-all active:scale-[0.98] text-lg"
            >
              <Icon name="download" className="text-2xl" />
              Download for Windows
            </a>
            <p className="mt-3 text-slate-500 text-xs font-medium uppercase tracking-widest">
              Version 1.1.5 • Windows 10/11
            </p>
            <p className="mt-2 text-slate-500 text-xs max-w-sm text-center leading-relaxed">
              Windows may show a "Windows protected your PC" warning. Click <span className="text-slate-300 font-medium">More info</span> then <span className="text-slate-300 font-medium">Run anyway</span> to proceed.
            </p>
            <a
              href={APP_GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-3 inline-flex items-center gap-1.5 text-slate-500 text-xs hover:text-slate-300 transition-colors"
            >
              <svg className="size-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.017C22 6.484 17.522 2 12 2Z" />
              </svg>
              View source on GitHub
            </a>
          </div>

          {/* Installation Steps */}
          <div className="mb-12">
            <div className="flex items-center gap-4 mb-6">
              <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400">
                Installation Steps
              </h3>
              <div className="h-px flex-1 bg-primary/20" />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              {STEPS.map(({ num, icon, title, desc }) => (
                <div
                  key={num}
                  className="bg-bg-surface p-6 rounded-xl border border-white/5 flex flex-col gap-4 relative overflow-hidden hover:border-primary/30 transition-colors"
                >
                  <div className="absolute -right-4 -top-4 w-24 h-24 bg-primary/5 rounded-full blur-2xl" />
                  <div className="flex items-center justify-between relative z-10">
                    <span className="text-4xl font-black text-gradient opacity-80">{num}</span>
                    <div className="p-2 bg-primary/10 rounded-lg">
                      <Icon name={icon} className="text-primary" />
                    </div>
                  </div>
                  <div className="relative z-10">
                    <h4 className="font-bold text-lg text-white">{title}</h4>
                    <p className="text-slate-400 text-sm mt-1 leading-relaxed">{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* System Requirements + FAQ in 2 columns */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Requirements */}
            <div className="bg-bg-surface rounded-xl p-6 border border-white/5">
              <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-5">
                System Requirements
              </h3>
              <ul className="space-y-3">
                {[
                  { icon: "desktop_windows", text: "Windows 10 or Windows 11" },
                  { icon: "brush", text: "Blender 4.0 or newer" },
                  { icon: "language", text: "Stable internet connection" },
                  { icon: "memory", text: "4 GB RAM minimum (8 GB recommended)" },
                ].map(({ icon, text }) => (
                  <li key={text} className="flex items-center gap-3 text-sm text-slate-200">
                    <div className="p-1.5 rounded-md bg-primary/10 shrink-0">
                      <Icon name={icon} className="text-primary text-base" />
                    </div>
                    {text}
                  </li>
                ))}
              </ul>
            </div>

            {/* FAQ */}
            <div className="bg-bg-surface rounded-xl p-6 border border-white/5">
              <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-5">
                Frequently Asked
              </h3>
              <div className="space-y-3">
                {FAQS.map(({ q, a }) => (
                  <details
                    key={q}
                    className="group rounded-lg border border-white/5 overflow-hidden"
                  >
                    <summary className="flex items-center justify-between font-medium p-4 cursor-pointer hover:bg-white/[0.02] transition-colors list-none text-sm">
                      <span>{q}</span>
                      <Icon
                        name="add"
                        className="text-slate-500 group-open:rotate-45 transition-transform"
                      />
                    </summary>
                    <p className="px-4 pb-4 text-slate-400 text-sm leading-relaxed">{a}</p>
                  </details>
                ))}
              </div>
            </div>
          </div>

        </div>
      </main>
    </div>
  );
}
