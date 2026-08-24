# Setting up Space Works — Open Source Makerspace Manager (plain-language guide)

This guide is for makerspace organisers who are **not** software developers. It walks you through
running Space Works on a computer at your space, step by step. You don't need to understand
the code — just follow along.

You'll need about **30 minutes** and one **always-on computer** (any spare PC, a Mini-PC, or an
Intel NUC) that stays on and connected to your network.

---

## Step 1 — Install Docker Desktop

Docker is the free "engine" that runs the app. Install it once:

1. Go to **https://www.docker.com/products/docker-desktop/**.
2. Download the version for your computer (Windows or Mac) and run the installer. On Windows,
   enable the WSL2 integration; H1 uses Linux host locks and Unix sockets.
3. Click through the installer (the defaults are fine), then **start Docker Desktop** and wait
   until it says it's running (a whale icon appears in your taskbar/menu bar).

> If Docker asks you to enable virtualization/WSL on Windows, accept — it sets it up for you.

## Step 2 — Download the app

1. Open the project's GitHub page in a browser.
2. Click the green **Code** button → **Download ZIP**.
3. **Unzip** it somewhere easy to find, e.g. your Desktop. You'll get a folder like
   `Makerspace-Manager`.

## Step 3 — Run the setup

This is the only "command" you'll run, and the script does the rest (it makes all the passwords
and security keys for you).

**On Windows:** open the folder from a WSL2 terminal and run `bash setup.sh`. The old direct
PowerShell/Compose route is deliberately refused because it cannot provide the root-owned Unix socket and
host `flock` used by restore safety.

**On Mac/Linux:**
1. Open the **Terminal** app.
2. Drag the folder onto the Terminal window to go into it (or type `cd ` then drag the folder),
   press Enter, then run:
   `bash setup.sh`

The script will ask you a few simple questions (press Enter to accept the suggestion in brackets):

| Question | What to type |
|---|---|
| Web address people will type | `localhost` to start (you can change it later) |
| Name of your makerspace | e.g. `Riverside Makerspace` |
| Admin login username | `admin` is fine |
| Admin email | your email |
| Admin password | type one, or leave blank and it makes a strong one for you |
| Automatic updates | press Enter for seven-day, backup-first update checks from successful `main` releases |

Then it builds and starts everything. **The first time takes a few minutes** — that's normal.

## Step 4 — Open it

When the script finishes it prints two web addresses. Open them in a browser:

- **Public catalog** — what your community sees (browse + request).
- **Staff console** (`…/admin`) — the React console where Space Managers, Inventory Managers,
  Guest Admins, Print Managers, and the Super Admin do day-to-day work.

The Django control plane is at `/control/` on the backend only. It is an operator-only tool and is
not exposed on the public website/port.

**Write down the admin username and password it shows.** If you let it generate a password, that
line is the only time it's displayed.

## Step 5 — Make it useful

Log into the **staff console** address (`/admin`) and:

1. **Add your inventory** — the tools and equipment people can borrow.
2. **Turn on public visibility** — open your makerspace and enable **"public inventory"** so it
   shows on the public catalog.
3. **Add your team** — create accounts for your staff and assign them a role (Space Manager,
   Inventory Manager, Guest Admin, Print Manager). Your staff use this **staff console** for
   everything. (See the roles table in the [README](../README.md#roles--permissions) — the
   roles are fixed by the system; you only choose who gets which one.)
4. **Check enabled modules** - in makerspace settings, enable the workflows your space actually
   uses. Public self-checkout/direct handout, 3D printing, stocktake, containers, QR tools, reports,
   transfers, and procurement are shown or hidden from the public/staff screens based on these module
   switches.
5. **(Optional) Email & Telegram alerts** - set your makerspace's email (SMTP) and Telegram bot in
   the staff console's **Integration settings**. These are stored encrypted and never shown again.
6. **(Optional) Decide who hears what** - in **Settings → Notification channels** you can tick which
   kinds of alert go out by email, Telegram, Slack, Mattermost or Discord, choose who receives each
   one, and reword the messages.

### Who gets told, and where

Out of the box, an alert goes to everyone whose job covers it — a booking alert reaches the people
who manage bookings. You do not have to configure anything for that to work.

If you want something different, three settings do it, all under **Settings → Notification
channels**:

- **Who gets notified** — pick recipients for one kind of alert: a role, one named member, everybody,
  or the person the message is about. Leaving it empty means "notify by role", which is the default.
  Anyone who has turned their own notifications off is never mailed, even if you pick them.
- **Rooms** — if you use Slack, Discord, Mattermost or Telegram, you can have more than one channel.
  Leave a room unrestricted and it hears everything; restrict it to a machine and it hears only that
  machine. Useful when the laser team and the print room are different people.
- **Email templates** — reword any message. Each one shows the details you can drop in (names, times,
  machine, and so on) and previews before you save. There is a reset button if you change your mind.

One rule the system enforces for you: messages written *for a member* ("your booking is confirmed")
only ever go to that member by email or phone, never into a shared chat channel where everyone could
read their name.

---

## Letting people on your network reach it

By default it's at `localhost` (only that computer). To let others at your space use it:

1. Find that computer's address on your network (its local IP, like `192.168.1.50`, or its
   hostname).
2. Re-run the setup once and enter that address when asked for the "web address", **or** edit the
   `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` lines in the `.env` file to include it, then run
   `SPACEWORKS_COMPOSE_BUILD_LAYER=1 scripts/spaceworks-compose.sh bundled up -d`.
3. People then visit `http://<that-address>/` in their browser.

> For a public website with a real domain and HTTPS, you'll want someone technical to put a
> reverse proxy (e.g. Caddy or Nginx with a certificate) in front and set `ENABLE_HTTPS=true`.
> See [self-hosting.md](self-hosting.md).

## No spare computer?

You have two good options before giving up:

1. **Partner with another makerspace.** This app can run **many makerspaces on one backend**. If a
   nearby makerspace already runs it on their server, ask them to add yours as another "tenant" —
   you'll get your own catalog, your own web address, and your own admin, all on their shared
   backend. Most makers are glad to help another space, and it's an easy way for them to contribute.
2. **Use a hosted database (Supabase).** If partnering isn't possible, you can host the app on a
   cloud platform and use a free **Supabase** Postgres database. This is more technical — see
   **Option C** in the [README](../README.md#hosting).

---

## Everyday operations

- **Start it / after a reboot:** Docker Desktop can auto-start the app, or run
  `SPACEWORKS_COMPOSE_BUILD_LAYER=1 scripts/spaceworks-compose.sh bundled up -d`.
- **Stop it:** `SPACEWORKS_COMPOSE_BUILD_LAYER=1 scripts/spaceworks-compose.sh bundled down`
  (your data is safe — it's kept in a database volume).
- **Update to a newer version:** guided installs check every seven days by default. Use
  **Staff console -> Platform settings -> Software updates** to control automatic installation or select
  **Update now**. Run `scripts/update.sh --force` on Linux or from WSL2 to update immediately; the updater backs up
  PostgreSQL and verifies the new release before marking it installed. If the new application fails,
  it automatically returns to the previous retained release. Your `.env` and data are preserved. The
  database snapshot is retained but never restored automatically, and it does not cover MinIO photos
  and files; back up the MinIO data volume separately.

## Something went wrong?

- **"Docker is not running"** — open Docker Desktop and wait for it to start, then try again.
- **The page won't load** — give it another minute on first run; the build takes time.
- **See what's happening:** run
  `SPACEWORKS_COMPOSE_BUILD_LAYER=1 scripts/spaceworks-compose.sh bundled logs backend`.
- Still stuck? Open an issue on GitHub describing what you did and what you saw.
