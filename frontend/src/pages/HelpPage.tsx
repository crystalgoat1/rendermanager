import { Link } from "wouter";
import { Icon } from "../components/Icon";
import { APP_DISPLAY_NAME } from "../brand";

const TOPICS = [
    {
        icon: "wifi_off",
        title: "App won't connect",
        items: [
            "Make sure your PC has an active internet connection.",
            `Check that the app is running in your system tray (look for the ${APP_DISPLAY_NAME} icon).`,
            "If the icon shows red, try right-clicking it and selecting Quit, then relaunch the app.",
            "Check your firewall settings. The app needs outbound HTTPS access.",
        ],
    },
    {
        icon: "hourglass_empty",
        title: "Render not starting",
        items: [
            "Verify that Blender is installed and the path is correct in the setup wizard.",
            "Make sure the .blend file has been uploaded to your workspace.",
            "Check that the app is not paused. Click the tray icon to see its status.",
            "If a previous job failed, try canceling it from the dashboard before submitting a new one.",
        ],
    },
    {
        icon: "system_update_alt",
        title: "How to update the app",
        items: [
            "Download the latest installer from the Download App page.",
            "Run it over the existing installation. Your settings and login will be preserved.",
            "No need to uninstall first.",
        ],
    },
    {
        icon: "build",
        title: "How to change Blender path or workspace",
        items: [
            "Open the app from your system tray and click the gear icon.",
            "This relaunches the setup wizard where you can change your Blender path and workspace folder.",
        ],
    },
    {
        icon: "devices",
        title: "Setting up a second render PC",
        items: [
            "Download and install the app on the additional machine.",
            `Sign in with the same ${APP_DISPLAY_NAME} account.`,
            "Each PC registers as a separate computer automatically. You can see all connected computers in your dashboard.",
        ],
    },
    {
        icon: "image_not_supported",
        title: "Preview not loading",
        items: [
            "Wait for the first frame to finish rendering. Previews appear after a frame is saved.",
            "If the preview stays blank, try refreshing your browser.",
            "For EXR renders, make sure the output format is set correctly in your .blend file.",
        ],
    },
];

export function HelpPage() {
    return (
        <div className="flex flex-col min-h-screen bg-bg-base">
            {/* Header */}
            <header className="sticky top-0 z-20 bg-bg-base/90 backdrop-blur-md border-b border-white/5 px-6 py-4 flex items-center gap-4">
                <Link href="/dashboard">
                    <button className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/5 transition-colors">
                        <Icon name="arrow_back" className="text-xl" />
                    </button>
                </Link>
                <h1 className="text-xl font-bold tracking-tight">Help</h1>
            </header>

            <main className="flex-1 p-6 pb-8">
                <div className="max-w-3xl mx-auto space-y-4">
                    {TOPICS.map(({ icon, title, items }) => (
                        <details
                            key={title}
                            className="group bg-bg-surface rounded-xl border border-white/5 overflow-hidden"
                        >
                            <summary className="flex items-center gap-4 p-5 cursor-pointer hover:bg-white/[0.02] transition-colors list-none select-none">
                                <div className="p-2 bg-primary/10 rounded-lg shrink-0">
                                    <Icon name={icon} className="text-primary text-lg" />
                                </div>
                                <span className="text-sm font-semibold text-white flex-1">{title}</span>
                                <Icon
                                    name="expand_more"
                                    className="text-slate-500 text-xl group-open:rotate-180 transition-transform"
                                />
                            </summary>
                            <ul className="px-5 pb-5 pl-16 space-y-2">
                                {items.map((item, i) => (
                                    <li key={i} className="text-sm text-slate-400 leading-relaxed flex items-start gap-2">
                                        <span className="text-slate-600 mt-0.5 shrink-0">•</span>
                                        {item}
                                    </li>
                                ))}
                            </ul>
                        </details>
                    ))}
                </div>
            </main>
        </div>
    );
}
