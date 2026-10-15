# Setting up Space Works — Open Source Makerspace Manager (plain-language guide)

This guide is for makerspace organisers who are **not** software developers. It walks you through
running Space Works on a computer at your space, step by step. You don't need to understand
the code — just follow along.

You'll need about **30 minutes** and one **always-on computer** (any spare PC, a Mini-PC, or an
Intel NUC) that stays on and connected to your network.

---

## Step 1 — Choose the host path

**Linux:** the curl installer below checks everything first, then offers to install Docker Engine,
Docker Compose V2 and curl through apt, dnf/yum, pacman or zypper after confirmation.
curl (or wget) and tar must already exist to read the questions. It supports x86_64 and aarch64.
It prints the dependency plan before making changes.

**Windows:** install and start [Docker Desktop](https://www.docker.com/products/docker-desktop/) with
Linux containers, then open **Git Bash**. Native Git Bash is supported for install, normal Compose
operation and upgrades. WSL2 is required only for restore/recovery operations described below.

**macOS:** install and start Docker Desktop before running the installer.

Docker Desktop installation on Windows/macOS:

1. Go to **https://www.docker.com/products/docker-desktop/**.
2. Download the version for your computer and run the installer. On Windows, keep the WSL2 engine
   enabled even when running ordinary commands from Git Bash.
3. Click through the installer (the defaults are fine), then **start Docker Desktop** and wait
   until it says it's running (a whale icon appears in your taskbar/menu bar).

> If Docker asks you to enable virtualization/WSL on Windows, accept — it sets it up for you.

## Step 2 — Run the pinned installer

On Linux, paste:

```bash
curl -fsSL https://raw.githubusercontent.com/SpaceWorks-HQ/SpaceWorks/main/install.sh | bash
```

It installs into `/opt/spaceworks` by default. To choose another directory, export it for the `bash`
side of the pipe:

```bash
curl -fsSL https://raw.githubusercontent.com/SpaceWorks-HQ/SpaceWorks/main/install.sh | SPACEWORKS_DIR="$HOME/SpaceWorks" bash
```

Use the second form in Windows Git Bash. The installer downloads the newest **tagged GitHub release**
archive—never a moving branch and never a Git clone—and runs that release's `setup.sh`. It checks the
architecture, dependencies, Docker, ports, disk space and install directory before installing a package
or creating the install root.

## Step 3 — Answer the setup questions

See [area follow-up questions](#area-follow-up-questions) for every area prompt and default.

The installer asks every deployment question before installing anything, shows one summary, and
continues only after `Proceed? [Y/n]`. It then hands confirmed answers to `setup.sh` privately;
setup generates the other passwords and security keys. WSL2 bash can be used instead of Git Bash on Windows.

The script will ask you a few simple questions (press Enter to accept the suggestion in brackets):

| Question | What to type |
|---|---|
| Hosting model | one space, several `/m/<slug>` spaces, or a subdomain platform |
| Website here? | yes, or API only (enter your external HTTPS website origins) |
| HTTPS | LAN HTTP, automatic Caddy (domain/email), or your existing proxy |
| How it runs | standard containers; single box is available for a local website over HTTP |
| File storage | bundled Silo, or your S3 buckets/credentials/public image URL |
| Areas | Inventory & lending, Machines and Reports default yes; Events, Bookings, Membership, Online payments and Chat default no. Each yes immediately asks its settings. |
| Web address people will type | `localhost` to start (you can change it later) |
| Name of your makerspace | e.g. `Riverside Makerspace` |
| Admin login username | `admin` is fine |
| Admin email | your email |
| Admin password | type one, or leave blank and it makes a strong one for you |
| Who can submit borrow requests? | members, signed-in accounts (default), or anyone |
| Optional integrations | Google Web client ID; Stripe secret/webhook keys and currency |
| GitHub repository | `SpaceWorks-HQ/SpaceWorks`, or your fork as `Owner/Repo` (asked before download by curl) |
| Automatic deploys | optional GitHub Actions runner; press Enter for No. Linux with systemd only; setup prints the GitHub steps |

The summary lists the selected services and whether the runner will be installed, and explains:
"migrate builds the database tables. It runs once and stops. It's required."
"orchestration is a start-up safety check. It runs once and stops. It's required."
Only after confirmation does setup ask silently for the short-lived GitHub registration token and
install a runner, if chosen. Existing-install updates preserve runner registration. See
[runner setup](self-hosting.md#install-the-runner-and-enable-deploys) for the required GitHub variable,
external-contributor approval, Idle/label check and organization runner-group settings. Read
[SECURITY](self-hosting.md#security): Docker access gives the runner effective root control.

Then it pulls the pinned release images and starts everything. **The first time takes a few minutes** —
that's normal. Developers with a full source checkout can explicitly use `bash setup.sh --build`; normal
installs never build Django or Vite locally.

## Step 4 — Open it

When the script finishes it prints two web addresses. Open them in a browser:

- **Public catalog** — what your community sees (browse + request).
- **Staff console** (`…/admin`) — the React console where Space Managers, Inventory Managers,
  custom handover staff, and the Super Admin do day-to-day work.

The Django control plane is at `/control/` on the backend only. It is an operator-only tool and is
not exposed on the public website/port.

**Write down the admin username and password it shows.** If you let it generate a password, that
line is the only time it's displayed.

## Step 5 — Make it useful

Log into the **staff console** address (`/admin`) and:

1. **Add your inventory** — the tools and equipment people can borrow.
2. **Turn on public visibility** — open your makerspace and enable **"public inventory"** so it
   shows on the public catalog.
3. **Add your team** — create accounts for staff and assign one of the protected default or custom
   action-based roles. Front-desk handover is a custom role, not a built-in Guest Admin role.
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
2. Edit the
   `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` lines in the `.env` file to include it, then run
   `scripts/spaceworks-compose.sh bundled up -d`.
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
  `scripts/spaceworks-compose.sh bundled up -d`.
- **Stop it:** `scripts/spaceworks-compose.sh bundled down`
  (your data is safe — it's kept in a database volume).
- **Update to a newer version:** guided installs pin the latest published GitHub release built from `main`.
  The optional server runner deploys the exact main release after images and the GitHub release are
  published. Enable it in your repository with `SPACEWORKS_DEPLOY=true` after applying the required
  [security settings](self-hosting.md#security). Forks use their own release workflow, runner and variable.
  See [Updating](self-hosting.md#updating). Run `bash scripts/update.sh --force` on Linux, macOS or Windows
  Git Bash to update immediately, optionally adding `--version X.Y.Z-main.<run>.<12-hex sha>`;
  the interactive command also opens the current area menu. The updater backs up
  PostgreSQL and verifies the new release before marking it installed. If the new application fails,
  it automatically returns to the previous retained release. Your `.env` and data are preserved. The
  database snapshot is retained but never restored automatically; forward migrations remain applied.
  The dump does not cover uploaded photos/files; back up object storage separately.
- **Change modules without upgrading:** run `bash scripts/update.sh --modules-only --makerspace <slug>`.
  With several makerspaces, select one slug or explicitly use `--all-makerspaces`; the updater never
  guesses. Use `--modules` to review the area menu during an update, or `--no-module-changes` to update only
  the release. Unticking asks for confirmation and retains all module data; install and update never run
  the separate destructive `purge_module_data` command.

Pasting the curl installer again over an install with `.spaceworks-version` opens a menu for update,
module changes, both, or cancel. A non-empty directory without that marker is refused instead of being
treated as a safe live deployment.

### Windows support boundary

- **Tier 1—native Git Bash:** install, Compose run/stop/logs, manual update and module changes. When the
  host has no `flock`, the updater uses its existing directory lock with owner PID and timestamp. A dead
  owner is detected and recovered; after verifying a misleading live/corrupt owner, `--override-lock`
  is the documented escape hatch.
- **Tier 2—WSL2:** in-place restore, backup import and compound host recovery. Those supervisors rely on
  Linux AF_UNIX sockets plus root-owned-file trust semantics. Run them from WSL2 with Docker Desktop's
  WSL integration; they are deliberately not ported to native Windows.

## Something went wrong?

- **"Docker is not running"** — open Docker Desktop and wait for it to start, then try again.
- **The page won't load** — give it another minute on first run; image download and startup take time.
- **See what's happening:** run
  `scripts/spaceworks-compose.sh bundled logs backend`.
- Still stuck? Open an issue on GitHub describing what you did and what you saw.

## Area follow-up questions

The eight area questions occur in this order, before the summary. Each yes immediately asks the
applicable follow-ups. Enter accepts the bracketed default. All answers appear in the summary and
private answers file. Areas map to [modules and features](MODULES.md#areas-used-by-setup). An existing events/bookings edition
preselects its corresponding area plus Membership, Online payments and Reports, keeping plans,
checkout and reporting; Inventory and Machines default off. Core, backup, notifications, email and
per-person accounts are always on. Accounts provide self sign-up, password/Google/Apple/phone
sign-in and the member area. Membership adds plans, vouching, renewals and the mobile app.

| Area question | Follow-ups in order (defaults) | Editable later |
| --- | --- | --- |
| Use Inventory & lending? [Y/n] | Maximum active loans [0]; outstanding items [0] (zero = unlimited); loan length [7 days]; maximum renewals [1]; renewal length [7 days]; self-checkout [Y/n]; kiosk [Y/n]; deposit mode [none] (`none/fixed/per_product`); fixed amount [0.00] if fixed; late fee/day [0.00]; cap [0.00] (zero = uncapped); fee grace [0 days]; require deposit settlement before issue [y/N] if using deposits; charge currency [usd]; who can submit borrow requests [accounts] (`accounts/anyone` while Membership is off) | General / loan policy, Features, loan charges, Borrow request access, Location & hours |
| Use Machines? [Y/n] | Enforce certification gating [Y/n] (blocks use until certified for the type); certification reminder lead [14 days]; maintenance reminder lead [7 days]. Zero disables advance notices. | Features, machine-type reminder policy |
| Use Events? [y/N] | New event audience [accounts] (`members/accounts/invite`); ticket currency [usd], reusing the shared charge currency if already answered. Promo codes, ticket types and offline check-in enabled. | Event defaults, each event/series, Location & hours |
| Use Bookings? [y/N] | No numeric follow-up: buffers and cancellation cutoff belong to each bookable resource; there is no space-level default. Recurring bookings enabled. | Bookable resource editor |
| Use Membership? [y/N] | Join mode [approval] (`approval/vouch/open/invite_only/closed`); if vouching: vouches [1], voucher tenure [30 days], pending applicants/voucher [3], vouch validity [30 days], vouches replace staff approval [y/N]; application form [Y/n] (editable question: why join); create first plan [y/N] (skippable); if chosen: name [Standard], interval [monthly] (`monthly/yearly/custom_days`), custom days [30] if applicable, amount [0.00], currency [usd], auto-renew [Y/n]; if renewing: open window [7 days], grace [0 days], retries [0], reminders before [14,7,1], after [none]. If lending is on, confirm who can submit requests [members]. | Membership admission and form builder, membership plans, Features |
| Use Online payments? [y/N] | Checkout for chosen domains is enabled; default checkout currency [usd] if no earlier area set it; Stripe keys remain optional integration questions later. Money owed and receipts remain enabled without this area. | Payment settings |
| Use Reports? [Y/n] | Reports and analytics for every installed module, saved views and scheduled exports; no numeric follow-ups. | Reports |
| Use Chat alerts? [y/N] | All five channels enabled and idle until configured; no token/URL questions here. | Integration settings |

Next, always asked:

1. Label this as an organization instead of a makerspace? [y/N]
2. Makerspace IANA timezone [UTC, or the host TZ value], then quiet hours start [22:00] and end [08:00], in the makerspace timezone. Equal times disable the window.
3. Daily digests on by default? [y/N]; if yes, delivery time [08:00]. Members can override this default.
4. Require two-step sign-in (MFA) for staff? [y/N]
5. Admin username [admin], email [required], password [auto-generate].
6. Google client ID [skip]; Stripe secret/webhook keys [skip] only with Online payments; checkout reuses the shared currency.
7. Repository [SpaceWorks-HQ/SpaceWorks] unless selected before download; optional Linux/systemd runner [y/N].
8. The summary lists areas, all settings and deployment actions, followed by Proceed? [Y/n].

The Membership module currently enforces members-only borrow requests. Enabling it explicitly
confirms the earlier request-access answer as members. Disable Membership to admit other accounts
or account-less requests; personal accounts remain on. Inventory off skips borrowing questions, keeps
the six core modules and hides lending without touching loan/evidence data. Enabling self-checkout or kiosk never bypasses
authentication, eligible-tool checks or evidence requirements.

Only Events (with optional Membership/Payments/Reports/Chat) derives the `events` edition; only
Bookings similarly derives `bookings`. Other combinations derive `makerspace`; the organization
question overrides the label to `organization`, without changing tenancy.

Change areas through installer menu 2/3 or `scripts/update.sh --modules-only`. The menu shows
on/partial/off, asks settings only for newly enabled areas, then confirms. Optional uninstalls
retain all data; Inventory off disables `loans.enabled`, and Membership off keeps personal accounts.
Automation can select an exact set using
`--areas=inventory,machines`, or retain the existing `--all-modules`, `--without=...`,
`--makerspace`, `--all-makerspaces` and `--confirm-removals` flags.
