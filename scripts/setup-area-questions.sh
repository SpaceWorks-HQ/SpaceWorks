#!/usr/bin/env bash
# Area follow-ups shared by the up-front questionnaire and the live change menu.
SETUP_AREAS=(inventory machines events bookings membership payments reports chat)
SETUP_AREA_LABELS=('Inventory & lending' Machines Events Bookings Membership 'Online payments' Reports 'Chat alerts')
AREA_SETTING_RECORDS=()
# Windows resumes with confirmed answers in the environment; sourcing this helper
# must not erase them before setup.sh can consume the private stdin document.
[[ -n "${AREA_SETTINGS_JSON:-}" ]] || AREA_SETTINGS_JSON='{}'
SETUP_SELECTED_AREAS="${SETUP_SELECTED_AREAS:-}"

area_yes() { [[ "$1" =~ ^([Yy]|yes|YES)$ ]]; }
area_question() {
  local section="$1" field="$2" type="$3" label="$4" default="$5" rule="$6"
  local variable="AREA_${section}_${field//./_}"
  question "$variable" "$label" "$default" "$rule" || return 1
  AREA_SETTING_RECORDS+=("$section|$field|$type|$variable|$label")
  [[ "$section:$field" != root:currency ]] || AREA_CURRENCY_ASKED=1
}
area_bool() { area_question "$1" "$2" bool "$3" "$4" choices:Y,y,yes,YES,N,n,no,NO; }
area_number() { area_question "$1" "$2" number "$3" "$4" "integer:$5:$6"; }

ask_inventory_settings() {
  echo 'Borrow limits count outstanding loans/items; zero means unlimited.'
  area_number loan_policy loan_max_active 'Maximum active loans per borrower' 0 0 2147483647 || return 1
  area_number loan_policy loan_max_items 'Maximum outstanding items per borrower' 0 0 2147483647 || return 1
  echo 'Renewals extend an issued loan within these limits; evidence and return duties still apply.'
  area_number loan_policy default_loan_days 'Default loan length (days)' 7 1 365 || return 1
  area_number loan_policy loan_max_renewals 'Maximum renewals per loan' 1 0 100 || return 1
  area_number loan_policy loan_renewal_days 'Length of each renewal (days)' 7 1 365 || return 1
  AREA_loan_policy_loan_renewal_mode=auto
  AREA_SETTING_RECORDS+=('loan_policy|loan_renewal_mode|string|AREA_loan_policy_loan_renewal_mode|Renewal mode')
  echo 'Self-checkout lets authenticated eligible borrowers issue QR tools with evidence.'
  area_bool features inventory.self_checkout 'Enable self-checkout?' Y || return 1
  echo 'Kiosk enables stations with a PIN and an authenticated staff operator lease.'
  area_bool features inventory.kiosk 'Enable kiosk stations?' Y || return 1
  echo 'Loan charges record money owed even when you collect it offline; zero amounts mean no charge.'
  area_question loan_charges loan_deposit_mode string 'Loan deposit mode (none/fixed/per_product)' none choices:none,fixed,per_product || return 1
  if [[ "$AREA_loan_charges_loan_deposit_mode" == fixed ]]; then
    area_question loan_charges loan_deposit_amount string 'Fixed deposit per loan' 0.00 money || return 1
  fi
  area_question loan_charges loan_late_fee_per_day string 'Late fee per day' 0.00 money || return 1
  area_question loan_charges loan_late_fee_cap string 'Late fee cap (0 = uncapped)' 0.00 money || return 1
  area_number loan_charges loan_grace_days 'Late fee grace period (days)' 0 0 32767 || return 1
  if [[ "$AREA_loan_charges_loan_deposit_mode" != none ]]; then
    area_bool loan_charges loan_deposit_blocks_issue 'Require deposit settlement before issuing?' N || return 1
  fi
  area_question root currency string 'Default currency for charges' "${AREA_root_currency:-usd}" currency || return 1
  echo 'Who can submit borrow requests? Membership, when enabled below, requires active members.'
  echo '  accounts = signed-in accounts; anyone = no account, rate-limited contact details.'
  question REQUEST_ACCESS 'Borrow requests (Membership off)' accounts choices:accounts,anyone || return 1
}

ask_machines_settings() {
  echo 'Certification gating blocks use until a member is certified for that machine type.'
  area_bool features machines.certifications 'Enforce machine certification gating?' Y || return 1
  echo 'Reminder leads apply to existing built-in and local machine types; change them later per type.'
  area_number machine_policy cert_reminder_days 'Certification expiry reminder lead (days; 0 disables advance notice)' 14 0 365 || return 1
  area_number machine_policy reminder_lead_days 'Maintenance reminder lead (days; 0 disables advance notice)' 7 0 365 || return 1
}

ask_events_settings() {
  echo 'The audience is the default for new events; staff can change it on each event.'
  area_question space event_default_registration_audience string 'Default registration audience (members/accounts/invite)' accounts choices:members,accounts,invite || return 1
  echo 'Ticket types and promo codes are enabled. Zero-priced events remain free.'
  if [[ "${AREA_CURRENCY_ASKED:-0}" == 1 ]]; then
    echo "Ticket prices use the shared default currency: $AREA_root_currency."
  else
    area_question root currency string 'Default currency for ticket prices' "${AREA_root_currency:-usd}" currency || return 1
  fi
}

ask_bookings_settings() {
  echo 'Bookings and recurring bookings are enabled. Buffer and cancellation cutoff are configured per bookable resource in the console (no space-level defaults).'
}

ask_membership_settings() {
  echo 'Join mode controls admission: approval = staff review; vouch = eligible members vouch; open = immediate; invite_only = staff invitation; closed = no joins.'
  area_question admission join_mode string 'How people join' approval choices:approval,vouch,open,invite_only,closed || return 1
  if [[ "$AREA_admission_join_mode" == vouch ]]; then
    echo 'Vouch rules decide how many eligible members must back an application.'
    area_number admission vouches_required 'Vouches required' 1 1 5 || return 1
    area_number admission voucher_min_tenure_days 'Minimum voucher tenure (days)' 30 0 3650 || return 1
    area_number admission voucher_pending_limit 'Pending applicants per voucher' 3 1 100 || return 1
    area_number admission vouch_expiry_days 'Vouch validity (days)' 30 1 365 || return 1
    area_bool admission vouch_replaces_approval 'Do vouches replace staff approval?' N || return 1
  fi
  echo 'The default application asks why the applicant wants to join; edit the form later in Membership admission.'
  area_bool admission application_schema 'Collect a membership application form?' Y || return 1
  echo 'A plan sets a recurring membership term and optional dues; plans can be added later.'
  question AREA_CREATE_PLAN 'Create the first membership plan?' N choices:Y,y,yes,YES,N,n,no,NO || return 1
  if area_yes "$AREA_CREATE_PLAN"; then
    area_question plan name string 'Plan name' Standard text || return 1
    area_question plan interval string 'Plan interval (monthly/yearly/custom_days)' monthly choices:monthly,yearly,custom_days || return 1
    [[ "$AREA_plan_interval" != custom_days ]] || area_number plan custom_days 'Custom interval length (days)' 30 1 36500 || return 1
    area_question plan amount string 'Plan amount (0 for free)' 0.00 money || return 1
    area_question plan currency string 'Plan currency' usd currency || return 1
    echo 'Automatic renewal records the next term charge without needing an online payment provider.'
    area_bool plan auto_renew 'Automatically renew memberships?' Y || return 1
    if area_yes "$AREA_plan_auto_renew"; then
      area_number plan renewal_open_days 'Open renewal this many days before expiry' 7 0 365 || return 1
      area_number plan renewal_grace_days 'Renewal grace period (days)' 0 0 365 || return 1
      area_number plan renewal_retries 'Automatic renewal retries' 0 0 3 || return 1
      area_question plan reminder_days_before days 'Reminder days before expiry (comma-separated, or none)' 14,7,1 days || return 1
      area_question plan reminder_days_after days 'Reminder days after expiry (comma-separated, or none)' none days || return 1
    fi
  fi
  if [[ ",${SETUP_SELECTED_AREAS}," == *,inventory,* ]]; then
    echo 'Membership enabled means borrow requests require active members. Disable the Membership area to admit other accounts.'
    question REQUEST_ACCESS 'Who can submit borrow requests?' members choices:members || return 1
  fi
}

ask_payments_settings() {
  echo 'Online payments enable checkout for chosen areas after a provider is configured. Debt tracking and receipts stay on without it.'
  if [[ "${AREA_CURRENCY_ASKED:-0}" == 1 ]]; then
    echo "Online checkout uses the shared default currency: $AREA_root_currency."
  else
    area_question root currency string 'Default currency for online checkout' "${AREA_root_currency:-usd}" currency || return 1
  fi
}
ask_reports_settings() { echo 'Reports and saved report views are enabled.'; }
ask_chat_settings() { echo 'Telegram, Slack, Mattermost, Discord and signed webhooks stay idle until their URL/token is configured in settings.'; }

ask_always_settings() {
  echo 'Schedules and notification windows use this IANA timezone; change it later in Location & hours.'
  area_question space timezone string 'Makerspace timezone for local schedules' "${TZ:-UTC}" timezone || return 1
  echo 'Quiet hours delay optional alerts in local time; safety messages stay immediate.'
  area_question notifications quiet_start string 'Quiet hours start (HH:MM)' 22:00 clock || return 1
  area_question notifications quiet_end string 'Quiet hours end (HH:MM; same time disables window)' 08:00 clock || return 1
  echo 'Daily digests batch optional email; members can override this default in their preferences.'
  area_bool notifications daily_digest_default 'Daily digests on by default?' N || return 1
  if area_yes "$AREA_notifications_daily_digest_default"; then
    area_question notifications digest_at string 'Daily digest delivery time (HH:MM)' 08:00 clock || return 1
  fi
  echo 'Two-step sign-in requires staff with actions to enrol an authenticator.'
  area_bool features security.staff_mfa_required 'Require two-step sign-in (MFA) for staff?' N || return 1
}

derive_setup_edition() {
  SPACEWORKS_EDITION=makerspace
  local primary=() area
  IFS=, read -ra selected <<< "$SETUP_SELECTED_AREAS"
  for area in ${selected[@]+"${selected[@]}"}; do
    case "$area" in inventory|machines|events|bookings) primary+=("$area") ;; esac
  done
  if [[ ${#primary[@]} == 1 && ( "${primary[0]}" == events || "${primary[0]}" == bookings ) ]]; then
    SPACEWORKS_EDITION="${primary[0]}"
  fi
  [[ "${AREA_ORGANIZATION:-N}" != Y ]] || SPACEWORKS_EDITION=organization
}

ask_setup_areas() {
  local index key default incoming="${SPACEWORKS_EDITION:-makerspace}"
  AREA_SETTING_RECORDS=(); SETUP_SELECTED_AREAS=''; REQUEST_ACCESS=accounts; AREA_CREATE_PLAN=N
  AREA_CURRENCY_ASKED=0; AREA_root_currency=''
  for ((index=0; index<${#SETUP_AREAS[@]}; index++)); do
    key="${SETUP_AREAS[index]}"; default=N
    case "$incoming:$key" in makerspace:inventory|makerspace:machines|makerspace:reports|organization:inventory|organization:machines|organization:reports|events:events|bookings:bookings|events:membership|events:payments|events:reports|bookings:membership|bookings:payments|bookings:reports) default=Y ;; esac
    echo "${SETUP_AREA_LABELS[index]} enables every module and supported feature in this area."
    question AREA_ENABLE "Use ${SETUP_AREA_LABELS[index]}?" "$default" choices:Y,y,yes,YES,N,n,no,NO || return 1
    if area_yes "$AREA_ENABLE"; then
      SETUP_SELECTED_AREAS+="${SETUP_SELECTED_AREAS:+,}$key"
      "ask_${key}_settings" || return 1
    fi
  done
  echo 'Organization changes labels; the same makerspace tenancy and permissions apply.'
  question AREA_ORGANIZATION 'Label this as an organization instead of a makerspace?' N choices:Y,y,yes,YES,N,n,no,NO || return 1
  area_yes "$AREA_ORGANIZATION" && AREA_ORGANIZATION=Y || AREA_ORGANIZATION=N
  derive_setup_edition
  ask_always_settings || return 1
  build_area_settings_json
}

setup_areas_summary() {
  printf '  Areas: %s; edition: %s\n' "${SETUP_SELECTED_AREAS:-none}" "$SPACEWORKS_EDITION"
  local index key state
  for ((index=0; index<${#SETUP_AREAS[@]}; index++)); do
    key="${SETUP_AREAS[index]}"; state=no
    [[ ",${SETUP_SELECTED_AREAS}," != *,$key,* ]] || state=yes
    printf '  %s: %s\n' "${SETUP_AREA_LABELS[index]}" "$state"
  done
  echo '  Always on: core modules, personal accounts (sign-up and member area), backup, notifications, email, money tracking, receipt documents, payment reminders, staff invitations and advisory geofence.'
  local record section field type variable label
  for record in ${AREA_SETTING_RECORDS[@]+"${AREA_SETTING_RECORDS[@]}"}; do
    IFS='|' read -r section field type variable label <<< "$record"
    printf '  %s: %s\n' "$label" "${!variable}"
  done
  if [[ ",${SETUP_SELECTED_AREAS}," == *,membership,* ]]; then
    area_yes "${AREA_CREATE_PLAN:-N}" && echo '  Initial membership plan: configured' || echo '  Initial membership plan: skipped or unchanged'
  fi
}

source "$(dirname "${BASH_SOURCE[0]}")/setup-areas-json.sh"
