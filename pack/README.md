# Pack layout
#
# pack/                 Gas City pack (import this — CONFIGURES vehicle)
#   pack.toml
#   formulas/           Formula v2 HOW (gluless-prove + check.exec)
#   contracts/          .glu Goals (not Formula identity)
#   scripts/            check.exec entrypoint (env/argv only)
#   examples/           validation-city fixture for gc formula show
#
# Operator path: gc formula show gluless-prove / gc sling --formula gluless-prove
# after importing this pack. Do not add [[gluless]] to city.toml.
