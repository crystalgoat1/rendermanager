"use client";

export default function PrivacyPolicy() {
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-200 py-20 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-4xl font-bold mb-8 text-white">Privacy Policy</h1>

        <div className="space-y-6 text-neutral-400">
          <p>Last Updated: March 2026</p>

          <p>
            Render Manager ("we", "us", or "our") lets you monitor and manage Blender renders
            remotely. Your blend files and final renders stay on your machine - we never upload
            or store them. This policy explains what data we do collect and how we handle it.
          </p>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">What We Collect</h2>

            <h3 className="text-lg font-medium mb-2 text-neutral-300">Account</h3>
            <ul className="list-disc pl-5 space-y-1 mb-4">
              <li>Email address (for login and notifications)</li>
              <li>Subscription status and Stripe customer ID (no card details - Stripe handles that)</li>
            </ul>

            <h3 className="text-lg font-medium mb-2 text-neutral-300">Project metadata</h3>
            <p className="mb-2">
              When the agent scans your workspace, it sends a list of <code>.blend</code> filenames
              (as relative paths, e.g. <code>projects/scene.blend</code> - not full system paths)
              along with render settings like engine, resolution, and frame range. This is how the
              dashboard lets you pick a file and pre-fill job settings.
            </p>

            <h3 className="text-lg font-medium mb-2 text-neutral-300">Job data</h3>
            <ul className="list-disc pl-5 space-y-1 mb-4">
              <li>Which blend file was rendered (relative path), frame range, render settings, and any overrides you set</li>
              <li>Job status, progress, timestamps, and failure reasons</li>
              <li>Temporary preview thumbnails (JPEG) uploaded during rendering for the live dashboard view</li>
            </ul>

            <h3 className="text-lg font-medium mb-2 text-neutral-300">Hardware telemetry</h3>
            <p className="mb-2">
              While a render is active or while you are viewing the dashboard, the agent sends
              system stats: CPU usage, RAM, disk space, and GPU info (model name, load, VRAM,
              temperature). This powers the system monitor on the dashboard and the VRAM recovery
              feature. Telemetry is <strong>not sent when idle</strong> and is not permanently
              stored in the database.
            </p>

            <h3 className="text-lg font-medium mb-2 text-neutral-300">What we do NOT collect</h3>
            <ul className="list-disc pl-5 space-y-1">
              <li>Your blend files, textures, or final rendered output - these never leave your machine</li>
              <li>Full file system paths (only relative paths within your workspace folder)</li>
              <li>IP addresses (hashed ephemerally for rate limiting, purged every 5 minutes, never stored)</li>
              <li>Machine hostname or operating system version</li>
              <li>Browsing history or third-party tracking cookies</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">How Long We Keep It</h2>
            <ul className="list-disc pl-5 space-y-2">
              <li><strong>Job history:</strong> Automatically deleted 90 days after creation. You can also delete individual jobs at any time from the History page.</li>
              <li><strong>Render previews:</strong> Temporary JPEG thumbnails are deleted within 30 minutes (Free) or 24 hours (Pro). Compiled MP4 animations are deleted within 24 hours.</li>
              <li><strong>Account data:</strong> Kept until you delete your account. You can request full account deletion at any time.</li>
              <li><strong>Hardware telemetry:</strong> Held in memory during active sessions only. Not written to the database.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">Who Can See Your Data</h2>
            <p className="mb-2">
              Your data is scoped to your account. Other users cannot see your jobs, files, or agents.
            </p>
            <p className="mb-2">
              Administrators may access account information and job history for support and
              troubleshooting purposes. All admin access is logged.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">Third-Party Services</h2>
            <p className="mb-2">We use the following services to operate Render Manager:</p>
            <ul className="list-disc pl-5 space-y-1">
              <li><strong>Supabase</strong> - database and authentication</li>
              <li><strong>Stripe</strong> - payment processing (we never see or store your card details)</li>
              <li><strong>Resend</strong> - transactional emails (render notifications, account emails)</li>
            </ul>
            <p className="mt-2">
              These services receive only the data necessary to perform their function. We do not sell
              or share your data with anyone else.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">Your Rights</h2>
            <ul className="list-disc pl-5 space-y-2">
              <li><strong>Delete jobs:</strong> Remove individual jobs from your history at any time.</li>
              <li><strong>Delete your account:</strong> Request full deletion of your account and all associated data by contacting us.</li>
              <li><strong>Export:</strong> Your blend files and renders are already on your machine - there is nothing to export from our servers.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">Open Source</h2>
            <p>
              Render Manager's agent, server, and frontend source code are publicly available
              under the AGPL-3.0 license. You can verify exactly what data is collected and how
              it is handled by reading the code
              at <a href="https://github.com/crystalgoat1/rendermanager" className="text-indigo-400 hover:underline">github.com/crystalgoat1/rendermanager</a>.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">Changes</h2>
            <p>
              We may update this policy from time to time. If we make significant changes, we will
              notify you via the dashboard or email.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">Contact</h2>
            <p>
              Questions? Email us at{" "}
              <a href="mailto:support@rendermanager.com" className="text-indigo-400 hover:underline">support@rendermanager.com</a>.
            </p>
          </section>

        </div>
      </div>
    </div>
  );
}
