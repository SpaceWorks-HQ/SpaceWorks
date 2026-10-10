"""One-to-one command ownership remaps; request/operation IDs are tenant scoped."""
# command is an explicit local ownership path in datasets_7c; all other
# constraints include makerspace. The uniqueness guard excludes those rules.
LABEL_UNIQUE_RULES = {}
