#!/usr/bin/env bash
# Bash-only JSON transport: no answers or JSON documents ever appear in argv.
area_json_string() {
  local value="$1"
  value="${value//\\/\\\\}"; value="${value//\"/\\\"}"
  value="${value//$'\t'/\\t}"; value="${value//$'\r'/\\r}"; value="${value//$'\n'/\\n}"
  printf '"%s"' "$value"
}

area_json_value() {
  local type="$1" value="$2" field="$3"
  if [[ "$field" == application_schema ]]; then
    if area_yes "$value"; then
      printf '%s' '[{"id":"reason","label":"Why would you like to join?","type":"paragraph","required":true,"options":[]}]'
    else printf null; fi
  else
    case "$type" in
      bool) area_yes "$value" && printf true || printf false ;;
      number) printf '%s' "$((10#$value))" ;;
      days) [[ "$value" == none ]] && printf '[]' || printf '[%s]' "$value" ;;
      *) area_json_string "$value" ;;
    esac
  fi
}

build_area_settings_json() {
  local section record s field type variable label comma root_comma=''
  AREA_SETTINGS_JSON="$({
    printf '{'
    for section in space loan_policy loan_charges admission plan machine_policy notifications features root; do
      comma=''
      local seen_fields=","
      for record in ${AREA_SETTING_RECORDS[@]+"${AREA_SETTING_RECORDS[@]}"}; do
        IFS='|' read -r s field type variable label <<< "$record"
        [[ "$s" == "$section" ]] || continue
        [[ "$seen_fields" != *",$field,"* ]] || continue
        seen_fields+="$field,"
        if [[ -z "$comma" ]]; then
          printf '%s' "$root_comma"; root_comma=,
          [[ "$section" == root ]] || { area_json_string "$section"; printf ':{'; }
        fi
        printf '%s' "$comma"; comma=,
        area_json_string "$field"; printf ':'
        area_json_value "$type" "${!variable}" "$field"
      done
      [[ -z "$comma" || "$section" == root ]] || printf '}'
    done
    printf '}'
  })"
}

setup_areas_json() {
  local area comma='' without_key
  printf '{"areas":['
  local selected=() omitted=()
  IFS=, read -ra selected <<< "$SETUP_SELECTED_AREAS"
  for area in ${selected[@]+"${selected[@]}"}; do
    [[ -n "$area" ]] || continue
    printf '%s' "$comma"; comma=,; area_json_string "$area"
  done
  printf '],"settings":%s' "$AREA_SETTINGS_JSON"
  if [[ ",${SETUP_SELECTED_AREAS}," == *,inventory,* && -n "${REQUEST_ACCESS:-}" ]]; then
    printf ',"request_access":'; area_json_string "$REQUEST_ACCESS"
  fi
  if [[ -n "${MODULE_WITHOUT:-}" ]]; then
    printf ',"without":['; comma=''
    IFS=, read -ra omitted <<< "$MODULE_WITHOUT"
    for without_key in ${omitted[@]+"${omitted[@]}"}; do
      printf '%s' "$comma"; comma=,; area_json_string "$without_key"
    done
    printf ']'
  fi
  printf '}\n'
}
