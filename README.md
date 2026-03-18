# Render Manager

The open-source agent for [Render Manager](https://rendermanager.com), remote render management for Blender.

Submit, monitor, and manage Blender render jobs from any device. Your PC does the rendering; the agent handles the rest.

## What This Is

Render Manager lets you queue render jobs from your phone, laptop, or any browser while your powerful workstation at home does the actual rendering. This repository contains the **agent** — the software that runs on your rendering machine.

**This is not a render farm.** You render on your own hardware. The agent connects to the Render Manager service to receive jobs, launch Blender, report progress, and upload frame previews.

## How It Works

```
Browser / Phone                Render Manager              Your PC
                               (cloud service)             (this agent)

Create a render job  -------->  Queues the job  -------->  Picks up job
Monitor progress     <--------  Tracks status   <--------  Reports progress
View live previews   <--------  Streams frames  <--------  Uploads JPEGs
                                                           Runs Blender CLI
```

1. The agent scans a local folder for `.blend` files and publishes their metadata
2. You create a job from the web dashboard (pick a file, set frame range, tweak settings)
3. The agent picks up the queued job and launches `blender --background` with your settings
4. Progress updates and JPEG previews stream back to the dashboard in real time
5. When done, the job is marked complete and you get a notification

Your `.blend` files never leave your machine — only file paths, metadata, and rendered frame previews are transmitted.

## Quick Start

**Recommended:** Download the installer from [rendermanager.com/download](https://rendermanager.com/download).

**From source:**

```bash
# Prerequisites: Python 3.10+, Blender installed, Windows 10/11
git clone https://github.com/crystalgoat1/rendermanager.git
cd rendermanager
pip install -r requirements-agent.txt
python agent_entry.py
```

On first run, the agent will guide you through linking your Render Manager account.

## Security

- **Token auth:** The agent authenticates via a per-user token provisioned through a PKCE OAuth flow. The token is stored locally in `%APPDATA%/RenderManager/agent_config.json` and sent via `X-Agent-Token` header, never in URLs.
- **Render overrides:** All render settings go through a strict allowlist with type and range validation (`agent_override.py`). No arbitrary code execution is possible.
- **No file uploads:** Your `.blend` files stay on your machine. Only file paths, scene metadata, and rendered frame previews (JPEGs) are sent to the server.
- **Open source:** This agent is fully open source so you can verify exactly what runs on your machine.

Report security vulnerabilities to **security@rendermanager.com** — see [SECURITY.md](SECURITY.md) for details.

## Project Structure

```
agent/
  agent_main.py          Event loop, heartbeat, job polling
  agent_render.py        Blender CLI execution, frame parsing
  agent_override.py      Render override script generation (allowlisted)
  agent_blend_info.py    Reads .blend metadata via headless Blender
  agent_blend_scan.py    Local folder scanning for .blend files
  agent_preview.py       Preview generation and upload
  agent_ui.py            Desktop GUI (customtkinter)
  agent_config.py        Configuration management
  brand.py               Version and branding constants
blender_addon/           Blender addon for submitting jobs directly from Blender
```

## Bug Reports

If you find a bug, please [open an issue](https://github.com/crystalgoat1/rendermanager/issues) with your agent version, OS, steps to reproduce, and any relevant logs from `agent_debug.log`.

## License

[GNU General Public License v3.0](LICENSE)

Copyright 2026 RenderManager
