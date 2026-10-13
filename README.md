<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0078D4&height=280&section=header&text=ULTRA%20FORWARD%20V2&fontSize=70&animation=fadeIn&fontAlignY=38&desc=Architected%20by%20Dhanpal%20Sharma&descAlignY=62&descFontSize=22" width="100%">
</p>

<p align="center">
  <a href="https://t.me/Dhanpal_Sharma">
    <img src="https://img.shields.io/badge/DEVELOPER-DHANPAL%20SHARMA-0078D4?style=for-the-badge&logo=telegram&logoColor=white">
  </a>
  <img src="https://img.shields.io/badge/STABILITY-HIGH-success?style=for-the-badge&logo=statuspage">
  <img src="https://img.shields.io/badge/LICENSE-MIT-yellow?style=for-the-badge">
</p>

---

### 🛡️ System Architecture
> **Ultra Forward** is a state-of-the-art content synchronization engine built on **Asynchronous Python**. It offers a seamless bridge between Telegram chats, enabling high-speed mirroring with advanced metadata preservation and automated content filtering.

---

### 🚀 Advanced Tech Stack
<p align="left">
  <a href="https://skillicons.dev">
    <img src="https://skillicons.dev/icons?i=py,mongodb,linux,docker,heroku,github,git,vscode" />
  </a>
</p>

| **Component** | **Description** |
| :--- | :--- |
| **Logic Core** | `Python 3.11+` built on `Pyrogram` (MTProto) |
| **Persistence** | `MongoDB Atlas` for decentralized user-data storage |
| **Scalability** | `Asynchronous Task Queuing` for concurrent processing |
| **Interface** | `Custom Inline Keyboard Engine` with real-time UI updates |

---

### 📦 Rapid Deployment Options

> [!IMPORTANT]  
> Ensure you have your `API_ID` and `API_HASH` ready before deployment.

<details>
<summary><b>☁️ Cloud Orchestration (Koyeb / Heroku)</b></summary>
<br>
<p align="center">
  <a href="https://app.koyeb.com/deploy?type=git&repository=github.com/Dhanpal-Sharma/Ultra-Forward-Bot&branch=main&name=ultra-forward-bot">
    <img src="https://www.koyeb.com/static/images/deploy/button.svg" width="180">
  </a>
  &nbsp;&nbsp;
  <a href="https://heroku.com/deploy?template=https://github.com/Dhanpal-Sharma/Ultra-Forward-Bot">
    <img src="https://www.herokucdn.com/deploy/button.svg" width="180">
  </a>
</p>
</details>

<details>
<summary><b>🖥️ Bare Metal / VPS Deployment</b></summary>

```bash
# Clone the repository
git clone [https://github.com/Dhanpal-Sharma/Ultra-Forward-Bot](https://github.com/Dhanpal-Sharma/Ultra-Forward-Bot)

# Enter the source directory
cd Ultra-Forward-Bot

# Prepare the environment
pip install -r requirements.txt

# Launch the engine
python3 -m bot
</details>

🕹️ Command Interface
<table width="100%"> <tr> <td width="50%" valign="top"> <b>🛠️ User Controls</b>


• <code>/start</code> - System Handshake


• <code>/forward</code> or <code>/fwd</code> - Start forwarding


• <code>/fwdstatus</code> - Show saved task progress/checkpoint


• <code>/settings</code> - Configure accounts and destinations


• <code>/reset</code> - Reset personal settings </td> <td width="50%" valign="top"> <b>🛡️ Admin Authority</b>


• <code>/broadcast</code> - Mass Notification


• <code>/restart</code> - Core Reboot


• <code>/resetall</code> - Database Flush </td> </tr> </table>

### ♻️ Durable forwarding recovery (MongoDB)

Forwarding tasks are now saved in MongoDB before processing begins. The bot stores the source cursor, task state, progress counters, status-message reference, and known failed source message IDs. After a Heroku/container restart, a recovery worker finds expired task leases and resumes active jobs from the last confirmed checkpoint instead of starting from message ID zero.

- Use `/fwdstatus` to inspect the latest task, its last confirmed source message ID, successful-forward count, and known failed message IDs.
- Keep `DATABASE_URI`/`DATABASE` pointed at persistent MongoDB. In-memory state and Heroku's local filesystem are not used as the recovery source of truth.
- Completed and manually cancelled jobs are not automatically restarted. Source-access problems are marked `needs_attention` until the access issue is fixed.
- Copy-mode checkpoints are committed after each message. Native-forward mode sends a batch and then checkpoints it; if the process dies after Telegram accepts a batch but before MongoDB commits its checkpoint, that one in-flight batch may be sent again on recovery. Telegram does not provide an idempotency key for forwarding, so exactly-once delivery cannot be guaranteed; the design prioritizes not skipping unconfirmed messages.
- Individual copy failures are recorded in `forward_job_failures` and the task ends as `completed_with_errors` so the failure count is visible instead of silently reporting full success.

✨ Premium Features
[!TIP] Performance Optimized: This bot uses dynamic sleep intervals to prevent Telegram FloodWaits during high-volume transfers.

[x] Cross-Chat Mirroring: Forward from restricted, private, or public chats.

[x] Userbot Integration: Seamlessly sync from private groups via User Accounts.

[x] Metadata Sanitizer: Remove ads, tracking links, or custom keywords.

[x] Real-time UX: Live percentage bars and dynamic ETA tracking.

[x] Durable job recovery: Resume interrupted forwarding from MongoDB checkpoints; an ambiguous in-flight native-forward batch may be replayed.

💎 Architect Branding
<p align="center"> <img src="https://www.google.com/search?q=https://github-readme-stats.vercel.app/api%3Fusername%3DDhanpal-Sharma%26show_icons%3Dtrue%26theme%3Dradical%26hide_border%3Dtrue%26bg_color%3D0D1117%26title_color%3D0078D4%26icon_color%3D0078D4" width="48%"> <img src="https://www.google.com/search?q=https://github-readme-stats.vercel.app/api/top-langs/%3Fusername%3DDhanpal-Sharma%26layout%3Dcompact%26theme%3Dradical%26hide_border%3Dtrue%26bg_color%3D0D1117%26title_color%3D0078D4" width="40%"> </p>

<p align="center"> <b>Connect with Dhanpal Sharma</b>


<a href="https://www.google.com/url?sa=E&source=gmail&q=https://t.me/Dhanpal_Sharma"><b>Telegram</b></a> • <a href="https://www.google.com/search?q=https://github.com/Dhanpal-Sharma"><b>GitHub</b></a> • <a href="mailto:contact@dhanpalsharma.me"><b>Professional Email</b></a> </p>

<p align="center"> <img src="https://www.google.com/search?q=https://img.shields.io/badge/2026-DHANPAL%2520SHARMA-0078D4%3Fstyle%3Dfor-the-badge"> </p>

<p align="center"> <i>© 2026 Premium Bot Solutions. All Rights Reserved.</i> </p>
