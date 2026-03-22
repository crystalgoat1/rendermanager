"use client";

export default function TermsOfService() {
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-200 py-20 px-4 sm:px-6 lg:px-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-4xl font-bold mb-8 text-white">Terms of Service</h1>
        
        <div className="space-y-6 text-neutral-400">
          <p>Last Updated: March 2026</p>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">1. Agreement to Terms</h2>
            <p>
              By accessing or using the Render Manager website (rendermanager.com) and the Render Manager Agent 
              software, you agree to be bound by these Terms of Service. If you disagree with any part of these terms, 
              you may not access the service.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">2. Description of Service</h2>
            <p>
              Render Manager provides a cloud-based rendering orchestration platform. This includes a web dashboard 
              for managing rendering jobs and a downloadable client agent ("Render Manager Agent") that connects local 
              hardware to the network to process these jobs using Blender.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">3. User Accounts</h2>
            <ul className="list-disc pl-5 space-y-2">
              <li>When you create an account, you must provide accurate, complete, and current information.</li>
              <li>You are responsible for safeguarding your password and for all activities that occur under your account.</li>
              <li>You agree not to disclose your password to any third party.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">4. Acceptable Use</h2>
            <p>You agree not to use the Service to:</p>
            <ul className="list-disc pl-5 space-y-2 mt-2">
              <li>Upload, transmit, or distribute any content that is illegal, defamatory, obscene, or infringes on any third party's intellectual property rights.</li>
              <li>Attempt to gain unauthorized access to our systems or other users' accounts.</li>
              <li>Distribute malware, viruses, or any other malicious code.</li>
              <li>Interfere with or disrupt the integrity or performance of the Service.</li>
            </ul>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">5. User Content</h2>
            <p>
              You retain all rights to the 3D files (e.g., `.blend` files), assets, and rendered outputs associated with your account. 
              Render Manager does not upload or process your heavy 3D files on our servers; rendering occurs entirely on the local hardware 
              running the Render Manager Agent. By utilizing the Service, you grant Render Manager a temporary license strictly limited to 
              processing lightweight metadata (such as filenames and render settings) and the final rendered output images or videos for 
              display in your web dashboard and delivery to your devices. We do not claim ownership of your work.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">6. Hardware and System Impact</h2>
            <p>
              By installing the Render Manager Agent, you acknowledge that it will utilize your computer's CPU, GPU, and memory. 
              Rendering processes are resource-intensive and may cause hardware to operate at maximum capacity, resulting in 
              increased power consumption and temperatures. You assume all responsibility and risk for running these workloads 
              on your hardware. We are not liable for any hardware failure or damage resulting from the use of our agent.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">7. Disclaimer of Warranties</h2>
            <p className="uppercase text-sm">
              The service is provided on an "as is" and "as available" basis without any warranties of any kind. 
              We disclaim all warranties, including, but not limited to, warranties of merchantability, fitness for a 
              particular purpose, and non-infringement. We do not warrant that the service will operate error-free or 
              that the service and its servers are free of computer viruses or other harmful mechanisms.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">8. Limitation of Liability</h2>
            <p className="uppercase text-sm">
              To the maximum extent permitted by law, Render Manager shall not be liable for any indirect, incidental, 
              special, consequential, or punitive damages, including without limitation, loss of profits, data, use, goodwill, 
              or other intangible losses, resulting from (i) your access to or use of or inability to access or use the service; 
              (ii) any conduct or content of any third party on the service; (iii) any content obtained from the service; and 
              (iv) unauthorized access, use or alteration of your transmissions or content.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">9. Modifications to Terms</h2>
            <p>
              We reserve the right to modify or replace these Terms at any time. If a revision is material, we will try to provide 
              at least 30 days' notice prior to any new terms taking effect. What constitutes a material change will be determined 
              at our sole discretion.
            </p>
          </section>

          <section>
            <h2 className="text-2xl font-semibold mb-3 text-neutral-200">10. Contact Us</h2>
            <p>
              If you have any questions about these Terms, please contact us at{" "}
              <a href="mailto:support@rendermanager.com" className="text-indigo-400 hover:underline">support@rendermanager.com</a>.
            </p>
          </section>

        </div>
      </div>
    </div>
  );
}
