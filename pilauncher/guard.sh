#!/bin/sh
# Eseguito da systemd prima di ogni avvio del launcher (ExecStartPre).
# Se dopo un aggiornamento la nuova versione non arriva a confermarsi (vedi core/updater.py)
# e viene riavviata più di 3 volte, torna alla versione precedente.
BASE="${PILAUNCHER_HOME:-/opt/pilauncher}"
DATA="$BASE/data"
[ -f "$DATA/pending" ] || exit 0
prev="$(cat "$DATA/pending")"
n="$(cat "$DATA/pending_tries" 2>/dev/null || echo 0)"
n=$((n + 1))
echo "$n" > "$DATA/pending_tries"
[ "$n" -le 3 ] && exit 0
bad="$(basename "$(readlink -f "$BASE/current")")"
if [ -n "$prev" ] && [ -d "$BASE/releases/$prev" ]; then
    ln -sfn "releases/$prev" "$BASE/current.new" && mv -Tf "$BASE/current.new" "$BASE/current"
    echo "$bad" > "$DATA/rolled_back"
    echo "pilauncher: $bad non parte, ripristinata $prev" >&2
fi
rm -f "$DATA/pending" "$DATA/pending_tries"
exit 0
